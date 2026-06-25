from __future__ import annotations

import random
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from backend.api.deps import services
from backend.services.analysis_engine import analyze_periods


router = APIRouter(prefix="/api/home", tags=["home"])

_SNAPSHOT_CACHE: dict[str, dict] = {}
_SNAPSHOT_TTL_SECONDS = 15 * 60


@router.get("/financial-snapshot")
def financial_snapshot(market: str = "ALL", refresh: bool = False, svc=Depends(services)):
    cache_key = market.upper()
    cached = _SNAPSHOT_CACHE.get(cache_key)
    if cached and not refresh and time.time() - cached["created_at"] < _SNAPSHOT_TTL_SECONDS:
        return {**cached["payload"], "cache_status": "HIT"}

    candidates = svc.data_service.top_companies(market)
    random.shuffle(candidates)
    errors = []
    for company in candidates[:10]:
        try:
            payload = _build_snapshot(svc.data_service, company)
            _SNAPSHOT_CACHE[cache_key] = {"created_at": time.time(), "payload": payload}
            return {**payload, "cache_status": "MISS"}
        except Exception as exc:
            errors.append("%s:%s" % (company.get("ticker"), str(exc)[:100]))
            continue

    raise HTTPException(
        status_code=502,
        detail="暂时没有可展示的首页财报快照。%s" % ("；".join(errors[:3]) if errors else ""),
    )


def _build_snapshot(data_service, company: dict) -> dict:
    company = data_service.ensure_complete_company(company)
    options = data_service.list_report_options(company)
    annual = options.get("annual") or []
    quarterly = options.get("quarterly") or []
    period_type = "annual" if annual else "quarterly"
    selected = (annual or quarterly)[:4]
    if not selected:
        raise ValueError("没有可用报告期")

    dataset = data_service.get_financial_dataset(company, periods=selected, period_type=period_type)
    analysis = analyze_periods(company, dataset, selected, period_type)
    latest = analysis["periods"][-1]
    metrics = latest.get("metrics", {})
    snapshot_metrics = _snapshot_metrics(metrics, company.get("market"))
    if len([item for item in snapshot_metrics if item.get("available")]) < 2:
        raise ValueError("可展示指标不足")

    return {
        "company": _company_payload(company),
        "period": analysis["latest_period"],
        "period_type": period_type,
        "summary": _compact_summary(analysis.get("summary") or "", company),
        "metrics": snapshot_metrics,
        "trend": _trend(analysis.get("periods", []), "revenue"),
        "health_label": _health_label(analysis.get("score")),
        "score": analysis.get("score"),
        "stance": analysis.get("stance"),
        "source": "财报掘金真实财务快照",
        "is_demo": False,
        "target_url": "/index.html?ticker=%s&market=%s" % (company["ticker"], company["market"]),
    }


def _company_payload(company: dict) -> dict:
    return {
        "id": company.get("id"),
        "ticker": company.get("ticker"),
        "name": company.get("name"),
        "market": company.get("market"),
        "industry": company.get("industry") or company.get("sector") or "行业待补充",
    }


def _snapshot_metrics(metrics: dict, market: Optional[str]) -> list[dict]:
    unit = "USD" if market == "US" else "CNY"
    keys = ["revenue", "net_profit", "gross_margin", "operating_cashflow"]
    fallback_labels = {
        "revenue": "营业收入",
        "net_profit": "净利润",
        "gross_margin": "毛利率",
        "operating_cashflow": "经营现金流",
    }
    result = []
    for key in keys:
        metric = metrics.get(key, {})
        display = metric.get("display") or "待补充"
        if key in {"revenue", "net_profit", "operating_cashflow"} and display != "待补充":
            display = _ensure_unit(display, unit)
        result.append({
            "key": key,
            "label": metric.get("label") or fallback_labels[key],
            "value": display,
            "change": _change_text(metric.get("yoy")),
            "available": display != "待补充",
        })
    return result


def _ensure_unit(display: str, unit: str) -> str:
    if any(mark in display for mark in ("USD", "CNY", "人民币", "美元")):
        return display
    return "%s %s" % (display, unit)


def _change_text(value) -> str:
    if value is None:
        return "同比待补充"
    prefix = "+" if value > 0 else ""
    return "同比 %s%s%%" % (prefix, value)


def _trend(periods: list[dict], metric_key: str) -> list[int]:
    values = []
    for period in periods:
        value = period.get("metrics", {}).get(metric_key, {}).get("value")
        if isinstance(value, (int, float)):
            values.append(value)
    if not values:
        return [42, 58, 64, 72]
    low, high = min(values), max(values)
    if high == low:
        return [64 for _ in values]
    return [max(18, min(96, round((value - low) / (high - low) * 78 + 18))) for value in values]


def _health_label(score) -> str:
    if not isinstance(score, (int, float)):
        return "待观察"
    if score >= 78:
        return "稳健"
    if score >= 62:
        return "中性"
    return "谨慎"


def _compact_summary(summary: str, company: dict) -> str:
    text = " ".join((summary or "").split())
    if not text:
        return "%s 的公开财报数据已接入，可进入财报掘金查看完整分析。" % company.get("name", "该公司")
    return text[:118] + ("..." if len(text) > 118 else "")
