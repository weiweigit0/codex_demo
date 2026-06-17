from __future__ import annotations

from typing import Dict, Iterable, List, Optional


METRIC_LABELS = {
    "revenue": "营业收入",
    "gross_profit": "毛利润",
    "net_profit": "净利润",
    "operating_cashflow": "经营现金流",
    "assets": "总资产",
    "liabilities": "总负债",
    "equity": "股东权益",
    "inventory": "存货",
    "receivables": "应收账款",
    "operating_income": "经营利润",
    "rd_expense": "研发费用",
}


def analyze_periods(
    company: dict,
    dataset: dict,
    selected_periods: Optional[List[str]],
    period_type: str,
) -> dict:
    records = dataset["records"]
    available = _filter_periods(records.keys(), period_type)
    periods = selected_periods or available[:4]
    periods = [period for period in periods if period in records]
    if not periods:
        raise ValueError("没有找到可分析的报告期，请换一个 ticker 或报告期。")

    normalized = [_normalize_record(records[period], records) for period in periods]
    normalized = sorted(normalized, key=lambda item: _period_sort_key(item["period"]))
    latest = normalized[-1]
    risks = _build_risks(latest)
    score = _score(latest, risks)
    stance = "positive" if score >= 78 else "neutral" if score >= 62 else "cautious"
    filings = _match_filings(latest, dataset.get("filings", {}))

    return {
        "company": company,
        "period_type": period_type,
        "selected_periods": periods,
        "latest_period": latest["period"],
        "periods": normalized,
        "metrics": latest["metrics"],
        "risks": risks,
        "score": score,
        "stance": stance,
        "summary": _summary(company, latest, risks),
        "business_model": _business_model(company),
        "highlights": _highlights(latest),
        "watch_metrics": _watch_metrics(risks),
        "comparison": _comparison(normalized),
        "trend_insights": _trend_insights(normalized),
        "fact_opinion": _fact_opinion(company, latest, risks),
        "sources": filings,
        "rag_chunks": _build_chunks(company, normalized, risks, filings),
        "disclaimer": "本内容仅用于财报信息理解和研究辅助，不构成任何投资建议。",
    }


def _filter_periods(keys: Iterable[str], period_type: str) -> List[str]:
    if period_type == "quarterly":
        filtered = [key for key in keys if not key.endswith("-FY")]
    else:
        filtered = [key for key in keys if key.endswith("-FY")]
    return sorted(filtered, key=_period_sort_key, reverse=True)


def _period_sort_key(period: str):
    year, fp = period.split("-")
    order = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4, "FY": 5}
    return int(year), order.get(fp, 0)


def _normalize_record(record: dict, all_records: Dict[str, dict]) -> dict:
    metrics = {}
    for key, value in record.get("metrics", {}).items():
        raw = value.get("value")
        metrics[key] = {
            "key": key,
            "label": METRIC_LABELS.get(key, key),
            "value": raw,
            "unit": value.get("unit"),
            "display": _money(raw, value.get("unit")),
            "concept": value.get("concept"),
            "source_accn": value.get("accn"),
            "yoy": _growth(record["period"], key, raw, all_records, offset_year=True),
            "qoq": _growth(record["period"], key, raw, all_records, offset_year=False),
        }

    revenue = _metric_value(metrics, "revenue")
    gross_profit = _metric_value(metrics, "gross_profit")
    net_profit = _metric_value(metrics, "net_profit")
    assets = _metric_value(metrics, "assets")
    liabilities = _metric_value(metrics, "liabilities")
    equity = _metric_value(metrics, "equity")

    metrics["gross_margin"] = _ratio_metric("毛利率", gross_profit, revenue)
    metrics["net_margin"] = _ratio_metric("净利率", net_profit, revenue)
    metrics["debt_ratio"] = _ratio_metric("资产负债率", liabilities, assets)
    metrics["roe"] = _ratio_metric("ROE", net_profit, equity)

    return {
        "period": record["period"],
        "fy": record.get("fy"),
        "fp": record.get("fp"),
        "form": record.get("form"),
        "filed": record.get("filed"),
        "end": record.get("end"),
        "metrics": metrics,
        "sources": record.get("sources", []),
    }


def _growth(period: str, key: str, value, records: Dict[str, dict], offset_year: bool):
    if value in (None, 0):
        return None
    year, fp = period.split("-")
    if offset_year:
        peer_period = f"{int(year) - 1}-{fp}"
    else:
        peer_period = _previous_period(period)
    if not peer_period:
        return None
    peer_value = records.get(peer_period, {}).get("metrics", {}).get(key, {}).get("value")
    if peer_value in (None, 0):
        return None
    return round((value - peer_value) / abs(peer_value) * 100, 2)


def _previous_period(period: str) -> Optional[str]:
    year, fp = period.split("-")
    order = ["Q1", "Q2", "Q3", "Q4"]
    if fp == "FY":
        return f"{int(year) - 1}-FY"
    idx = order.index(fp)
    if idx == 0:
        return f"{int(year) - 1}-Q4"
    return f"{year}-{order[idx - 1]}"


def _metric_value(metrics: dict, key: str):
    return metrics.get(key, {}).get("value")


def _ratio_metric(label: str, numerator, denominator):
    if numerator is None or denominator in (None, 0):
        value = None
    else:
        value = round(numerator / denominator * 100, 2)
    return {
        "key": label,
        "label": label,
        "value": value,
        "display": "待补充" if value is None else f"{value}%",
        "concept": "calculated",
        "yoy": None,
        "qoq": None,
    }


def _build_risks(period: dict) -> List[dict]:
    metrics = period["metrics"]
    revenue_yoy = metrics.get("revenue", {}).get("yoy")
    profit_yoy = metrics.get("net_profit", {}).get("yoy")
    cashflow = _metric_value(metrics, "operating_cashflow")
    debt_ratio = _metric_value(metrics, "debt_ratio")
    receivables_yoy = metrics.get("receivables", {}).get("yoy")
    inventory_yoy = metrics.get("inventory", {}).get("yoy")
    gross_margin = _metric_value(metrics, "gross_margin")

    risks = [
        _risk(
            "收入增长",
            "yellow" if revenue_yoy is None or revenue_yoy < 5 else "green",
            "缺少同比数据，需要补充历史期。"
            if revenue_yoy is None
            else f"收入同比{_pct_text(revenue_yoy)}。",
        ),
        _risk(
            "利润质量",
            "yellow"
            if profit_yoy is not None and revenue_yoy is not None and profit_yoy < revenue_yoy - 8
            else "green",
            "净利润增速明显低于收入增速。" if profit_yoy is not None and revenue_yoy is not None and profit_yoy < revenue_yoy - 8 else "利润与收入没有明显背离。",
        ),
        _risk(
            "现金流",
            "red" if cashflow is not None and cashflow < 0 else "green",
            f"经营现金流为{metrics.get('operating_cashflow', {}).get('display', _money(cashflow))}。",
        ),
        _risk(
            "应收账款",
            "yellow"
            if receivables_yoy is not None and revenue_yoy is not None and receivables_yoy > revenue_yoy + 10
            else "green",
            "应收账款增速显著高于收入增速。" if receivables_yoy is not None and revenue_yoy is not None and receivables_yoy > revenue_yoy + 10 else "未发现应收账款明显异常。",
        ),
        _risk(
            "存货",
            "yellow"
            if inventory_yoy is not None and revenue_yoy is not None and inventory_yoy > revenue_yoy + 10
            else "green",
            "存货增速显著高于收入增速。" if inventory_yoy is not None and revenue_yoy is not None and inventory_yoy > revenue_yoy + 10 else "未发现库存明显异常。",
        ),
        _risk(
            "负债压力",
            "red" if debt_ratio is not None and debt_ratio > 75 else "yellow" if debt_ratio is not None and debt_ratio > 60 else "green",
            "资产负债率待补充。" if debt_ratio is None else f"资产负债率为{debt_ratio}%。",
        ),
        _risk(
            "盈利能力",
            "yellow" if gross_margin is not None and gross_margin < 20 else "green",
            "毛利率偏低，需要看行业属性。" if gross_margin is not None and gross_margin < 20 else "毛利率暂未显示明显压力。",
        ),
    ]
    return risks


def _risk(name: str, level: str, reason: str) -> dict:
    return {"name": name, "level": level, "reason": reason}


def _score(period: dict, risks: List[dict]) -> int:
    metrics = period["metrics"]
    score = 72
    revenue_yoy = metrics.get("revenue", {}).get("yoy")
    profit_yoy = metrics.get("net_profit", {}).get("yoy")
    cashflow = _metric_value(metrics, "operating_cashflow")
    gross_margin = _metric_value(metrics, "gross_margin")

    if revenue_yoy is not None:
        score += 7 if revenue_yoy >= 10 else -8 if revenue_yoy < 0 else 1
    if profit_yoy is not None:
        score += 7 if profit_yoy >= 10 else -10 if profit_yoy < 0 else 1
    if cashflow is not None:
        score += 5 if cashflow > 0 else -12
    if gross_margin is not None:
        score += 3 if gross_margin >= 35 else -4 if gross_margin < 15 else 0

    for risk in risks:
        if risk["level"] == "yellow":
            score -= 3
        elif risk["level"] == "red":
            score -= 9
    return max(0, min(100, round(score)))


def _summary(company: dict, latest: dict, risks: List[dict]) -> str:
    metrics = latest["metrics"]
    revenue = metrics.get("revenue", {})
    profit = metrics.get("net_profit", {})
    cashflow = metrics.get("operating_cashflow", {})
    active_risks = [risk["name"] for risk in risks if risk["level"] != "green"]
    risk_text = f"但{ '、'.join(active_risks) }需要继续观察" if active_risks else "暂未识别到突出风险"
    return (
        f"{company['name']}在{latest['period']}实现收入{revenue.get('display', '待补充')}，"
        f"净利润{profit.get('display', '待补充')}，经营现金流{cashflow.get('display', '待补充')}，"
        f"{risk_text}。"
    )


def _business_model(company: dict) -> str:
    if company.get("market") == "CN":
        return (
            f"{company['name']}为 A 股上市公司。当前版本基于巨潮资讯公告 PDF 抓取、文本解析和上传/粘贴文本进行分析，"
            "PDF 表格抽取结果会受公告版式影响。"
        )
    return (
        f"{company['name']}为 SEC 披露公司。当前 MVP 主要基于 XBRL 结构化财务数据分析，"
        "业务模式需要结合 10-K/10-Q 的 Business 与 MD&A 章节进一步解析。"
    )


def _highlights(period: dict) -> List[str]:
    metrics = period["metrics"]
    highlights = []
    if (metrics.get("revenue", {}).get("yoy") or 0) >= 10:
        highlights.append("收入同比保持双位数增长。")
    if (metrics.get("net_profit", {}).get("yoy") or 0) >= 10:
        highlights.append("净利润增长较快，盈利结果改善。")
    if (_metric_value(metrics, "operating_cashflow") or 0) > 0:
        highlights.append("经营现金流为正，利润质量更有支撑。")
    if not highlights:
        highlights.append("暂无特别突出的增长亮点，需要结合更多报告文本判断。")
    return highlights


def _watch_metrics(risks: List[dict]) -> List[str]:
    watch = [risk["name"] for risk in risks if risk["level"] != "green"]
    return (watch + ["营业收入", "净利润", "经营现金流"])[:5]


def _comparison(periods: List[dict]) -> dict:
    rows = []
    for period in periods:
        metrics = period["metrics"]
        rows.append(
            {
                "period": period["period"],
                "revenue": metrics.get("revenue", {}).get("display", "待补充"),
                "revenue_yoy": metrics.get("revenue", {}).get("yoy"),
                "net_profit": metrics.get("net_profit", {}).get("display", "待补充"),
                "net_profit_yoy": metrics.get("net_profit", {}).get("yoy"),
                "gross_margin": metrics.get("gross_margin", {}).get("display", "待补充"),
                "net_margin": metrics.get("net_margin", {}).get("display", "待补充"),
                "roe": metrics.get("roe", {}).get("display", "待补充"),
                "operating_cashflow": metrics.get("operating_cashflow", {}).get("display", "待补充"),
                "debt_ratio": metrics.get("debt_ratio", {}).get("display", "待补充"),
                "rd_expense": metrics.get("rd_expense", {}).get("display", "待补充"),
            }
        )
    return {"rows": rows}


def _trend_insights(periods: List[dict]) -> List[str]:
    if len(periods) < 2:
        return ["当前只选择了一个报告期，建议选择多个年度或季度观察趋势。"]
    first = periods[0]["metrics"]
    latest = periods[-1]["metrics"]
    insights = []
    for key, label in [("revenue", "收入"), ("net_profit", "净利润"), ("operating_cashflow", "经营现金流")]:
        start = _metric_value(first, key)
        end = _metric_value(latest, key)
        if start in (None, 0) or end is None:
            continue
        change = round((end - start) / abs(start) * 100, 2)
        insights.append(f"{label}较首期{'增长' if change >= 0 else '下降'}{abs(change)}%。")
    if not insights:
        insights.append("多期关键指标不足，需要补充结构化数据。")
    return insights


def _fact_opinion(company: dict, latest: dict, risks: List[dict]) -> dict:
    metrics = latest["metrics"]
    facts = [
        f"{latest['period']}收入为{metrics.get('revenue', {}).get('display', '待补充')}",
        f"净利润为{metrics.get('net_profit', {}).get('display', '待补充')}",
        f"经营现金流为{metrics.get('operating_cashflow', {}).get('display', '待补充')}",
    ]
    inferences = [risk["reason"] for risk in risks if risk["level"] != "green"]
    return {
        "facts": facts,
        "inferences": inferences or ["暂未识别到突出异常。"],
        "view": f"{company['name']}当前结论应围绕基本面理解，不构成交易建议。",
    }


def _match_filings(latest: dict, filings: dict) -> List[dict]:
    matched = []
    for accn in latest.get("sources", [])[:5]:
        filing = filings.get(accn)
        if filing:
            matched.append({"accession": accn, **filing})
    return matched


def _build_chunks(company: dict, periods: List[dict], risks: List[dict], filings: List[dict]) -> List[dict]:
    chunks = []
    for period in periods:
        metrics = period["metrics"]
        chunks.append(
            {
                "title": f"{period['period']} 核心指标",
                "content": (
                    f"{company['name']} {period['period']} 收入 {metrics.get('revenue', {}).get('display', '待补充')}，"
                    f"净利润 {metrics.get('net_profit', {}).get('display', '待补充')}，"
                    f"经营现金流 {metrics.get('operating_cashflow', {}).get('display', '待补充')}，"
                    f"毛利率 {metrics.get('gross_margin', {}).get('display', '待补充')}，"
                    f"资产负债率 {metrics.get('debt_ratio', {}).get('display', '待补充')}。"
                ),
            }
        )
    chunks.append({"title": "风险雷达", "content": " ".join([f"{r['name']}：{r['reason']}" for r in risks])})
    if filings:
        chunks.append(
            {
                "title": "来源",
                "content": " ".join([f"{item['form']} {item.get('filing_date')} {item['url']}" for item in filings]),
            }
        )
    return chunks


def _pct_text(value):
    if value is None:
        return "待补充"
    return f"{'增长' if value >= 0 else '下降'}{abs(value)}%"


def _money(value, unit: Optional[str] = "USD"):
    if value is None:
        return "待补充"
    suffix = unit or "USD"
    abs_value = abs(value)
    sign = "-" if value < 0 else ""
    if abs_value >= 1_000_000_000:
        return f"{sign}{abs_value / 1_000_000_000:.2f}B {suffix}"
    if abs_value >= 1_000_000:
        return f"{sign}{abs_value / 1_000_000:.2f}M {suffix}"
    return f"{sign}{abs_value:.0f} {suffix}"
