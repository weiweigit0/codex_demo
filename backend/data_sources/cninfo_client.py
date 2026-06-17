from __future__ import annotations

import re
import time
from datetime import datetime
from io import BytesIO
from typing import Dict, Iterable, List, Optional

import requests


CNINFO_QUERY_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_PDF_BASE_URL = "http://static.cninfo.com.cn/"
CNINFO_HEADERS = {
    "User-Agent": "Mozilla/5.0 FinancialReportMining/0.3",
    "Referer": "http://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search",
}

REPORT_CATEGORIES = "category_ndbg_szsh;category_yjdbg_szsh;category_bndbg_szsh;category_sjdbg_szsh;"
METRIC_PATTERNS = {
    "revenue": [r"营业收入"],
    "net_profit": [r"归属于上市公司股东的净利润", r"净利润"],
    "operating_cashflow": [r"经营活动产生的现金流量净额"],
    "assets": [r"资产总额", r"总资产"],
    "equity": [r"归属于上市公司股东的净资产", r"所有者权益合计", r"股东权益合计"],
    "liabilities": [r"(?<!流动)负债合计", r"总负债"],
    "inventory": [r"存货"],
    "receivables": [r"应收账款"],
    "rd_expense": [r"研发费用"],
}


class CninfoError(RuntimeError):
    pass


class CninfoClient:
    def __init__(self):
        self._announcements_cache: Dict[str, List[dict]] = {}
        self._dataset_cache: Dict[str, dict] = {}
        self._last_request = 0.0

    def list_reports(self, company: dict, limit: int = 12) -> List[dict]:
        reports = []
        for announcement in self._announcements(company):
            period = _period_from_title(announcement.get("announcementTitle", ""))
            if not period:
                continue
            report_type = "annual" if period.endswith("-FY") else "quarterly"
            reports.append(
                {
                    "id": f"CN-{company['ticker']}-{period}",
                    "company_id": company["id"],
                    "report_type": report_type,
                    "period": period,
                    "publish_date": _date_from_millis(announcement.get("announcementTime")),
                    "source_url": self.pdf_url(announcement),
                    "parse_status": "cninfo_pdf",
                    "announcement_id": announcement.get("announcementId"),
                    "title": _clean_title(announcement.get("announcementTitle", "")),
                }
            )
        return _unique_periods(reports)[:limit]

    def list_prospectuses(self, company: dict, limit: int = 8) -> List[dict]:
        documents = []
        for announcement in self._query_announcements(
            company,
            category="",
            searchkey="招股说明书",
            se_date="2000-01-01~2030-12-31",
            page_size=50,
        ):
            title = _clean_title(announcement.get("announcementTitle", ""))
            if not _is_supported_prospectus(title):
                continue
            publish_date = _date_from_millis(announcement.get("announcementTime"))
            announcement_id = announcement.get("announcementId")
            documents.append(
                {
                    "id": f"CN-{company['ticker']}-PROSPECTUS-{announcement_id or publish_date or len(documents)}",
                    "company_id": company["id"],
                    "report_type": "prospectus",
                    "period": publish_date or "prospectus",
                    "publish_date": publish_date,
                    "source_url": self.pdf_url(announcement),
                    "parse_status": "cninfo_pdf",
                    "announcement_id": announcement_id,
                    "title": title,
                }
            )
        return documents[:limit]

    def fetch_financial_dataset(
        self,
        company: dict,
        periods: Optional[List[str]] = None,
        period_type: str = "annual",
    ) -> dict:
        cache_key = company["ticker"]
        cached = self._dataset_cache.setdefault(cache_key, {"records": {}, "filings": {}})

        parse_errors = []
        reports = self._target_reports(company, periods=periods, period_type=period_type)

        for report in reports:
            if report["period"] in cached["records"]:
                continue
            try:
                text = self.extract_pdf_text(report["source_url"])
                record = self.parse_report_text(text, report)
            except Exception as exc:
                parse_errors.append(f"{report['period']} {exc}")
                continue
            if len(record["metrics"]) < 3:
                parse_errors.append(f"{report['period']} 可识别指标不足")
                continue
            cached["records"][record["period"]] = record
            accession = record["sources"][0]
            cached["filings"][accession] = {
                "form": record["form"],
                "report_date": record["end"],
                "filing_date": record["filed"],
                "url": report["source_url"],
            }

        selected = {report["period"] for report in reports}
        records = {
            period: record
            for period, record in cached["records"].items()
            if not selected or period in selected
        }
        filings = cached["filings"]

        if not records:
            reason = "；".join(parse_errors[:3]) or "未找到可解析的年度/季度报告 PDF"
            raise CninfoError(f"巨潮 PDF 解析失败：{reason}")

        return {"records": records, "filings": filings}

    def extract_pdf_text(self, url: str) -> str:
        self._throttle()
        response = requests.get(url, headers=CNINFO_HEADERS, timeout=25)
        response.raise_for_status()
        content = response.content
        try:
            pages = _extract_pages(content, max_pages=120)
            text = "\n".join(pages)
        except Exception as exc:
            raise CninfoError(f"PDF 文本抽取失败：{exc}") from exc

        if len(text.strip()) < 200:
            raise CninfoError("PDF 文本过少，可能是扫描件或表格抽取失败。")
        return text

    def parse_report_text(self, text: str, report: dict) -> dict:
        normalized = _normalize_text(text)
        metrics = {}
        for key, patterns in METRIC_PATTERNS.items():
            value = _find_metric(normalized, key, patterns)
            if value is not None:
                metrics[key] = _metric(value, key, report)

        if "operating_income" not in metrics and "net_profit" in metrics:
            metrics["operating_income"] = _metric(metrics["net_profit"]["value"], "operating_income", report)
        if "liabilities" not in metrics and "assets" in metrics and "equity" in metrics:
            metrics["liabilities"] = _metric(metrics["assets"]["value"] - metrics["equity"]["value"], "liabilities", report)
        _normalize_metric_scale(metrics)
        _normalize_balance_sheet_scale(metrics)

        return {
            "period": report["period"],
            "fy": int(report["period"].split("-")[0]),
            "fp": report["period"].split("-")[1],
            "form": "年度报告" if report["report_type"] == "annual" else "季度报告",
            "filed": report.get("publish_date"),
            "end": _period_end(report["period"]),
            "metrics": metrics,
            "sources": [report.get("announcement_id") or report["id"]],
        }

    def pdf_url(self, announcement: dict) -> str:
        return CNINFO_PDF_BASE_URL + announcement["adjunctUrl"]

    def _announcements(self, company: dict) -> List[dict]:
        cache_key = company["ticker"]
        if cache_key in self._announcements_cache:
            return self._announcements_cache[cache_key]
        announcements = self._query_announcements(
            company,
            category=REPORT_CATEGORIES,
            searchkey="",
            se_date="2020-01-01~2030-12-31",
            page_size=30,
        )
        filtered = [item for item in announcements if _is_supported_report(item.get("announcementTitle", ""))]
        self._announcements_cache[cache_key] = filtered
        return filtered

    def _query_announcements(
        self,
        company: dict,
        category: str,
        searchkey: str,
        se_date: str,
        page_size: int,
    ) -> List[dict]:
        org_id = company.get("org_id")
        if not org_id:
            raise CninfoError(f"{company['name']} 缺少巨潮 orgId，无法查询公告。")
        self._throttle()
        response = requests.post(
            CNINFO_QUERY_URL,
            headers=CNINFO_HEADERS,
            data={
                "pageNum": "1",
                "pageSize": str(page_size),
                "column": "szse",
                "tabName": "fulltext",
                "plate": "",
                "stock": f"{company['ticker']},{org_id}",
                "searchkey": searchkey,
                "secid": "",
                "category": category,
                "trade": "",
                "seDate": se_date,
                "sortName": "",
                "sortType": "",
                "isHLtitle": "true",
            },
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("announcements") or []

    def _target_reports(
        self,
        company: dict,
        periods: Optional[List[str]],
        period_type: str,
    ) -> List[dict]:
        reports = self.list_reports(company, limit=12)
        if periods:
            requested = set(periods)
            return [report for report in reports if report["period"] in requested]
        expected_type = "quarterly" if period_type == "quarterly" else "annual"
        return [report for report in reports if report["report_type"] == expected_type][:4]

    def _throttle(self):
        elapsed = time.time() - self._last_request
        if elapsed < 0.3:
            time.sleep(0.3 - elapsed)
        self._last_request = time.time()


def _is_supported_report(title: str) -> bool:
    clean = _clean_title(title)
    if any(word in clean for word in ["摘要", "英文", "取消", "审计报告", "社会责任", "环境"]):
        return False
    return _period_from_title(clean) is not None


def _is_supported_prospectus(title: str) -> bool:
    clean = _clean_title(title)
    if "招股说明书" not in clean:
        return False
    excluded = ["摘要", "提示性公告", "上市公告书", "发行结果", "路演", "保荐", "法律意见", "审计报告"]
    return not any(word in clean for word in excluded)


def _extract_pages(content: bytes, max_pages: int) -> List[str]:
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(BytesIO(content))
        return [(page.extract_text() or "") for page in reader.pages[:max_pages]]
    except Exception:
        try:
            import PyPDF2  # type: ignore

            reader = PyPDF2.PdfFileReader(BytesIO(content))
            return [
                reader.getPage(page_number).extractText() or ""
                for page_number in range(min(reader.getNumPages(), max_pages))
            ]
        except Exception as exc:
            raise CninfoError("当前环境未安装可用的 pypdf/PyPDF2，无法解析巨潮 PDF。") from exc


def _period_from_title(title: str) -> Optional[str]:
    clean = _clean_title(title)
    match = re.search(r"(20\d{2})\s*年\s*(年度|第一季度|一季度|半年度|第三季度|三季度)", clean)
    if not match:
        return None
    year, kind = match.groups()
    if kind == "年度":
        return f"{year}-FY"
    if kind in {"第一季度", "一季度"}:
        return f"{year}-Q1"
    if kind == "半年度":
        return f"{year}-Q2"
    if kind in {"第三季度", "三季度"}:
        return f"{year}-Q3"
    return None


def _find_metric(text: str, key: str, patterns: Iterable[str]) -> Optional[int]:
    preferred = _preferred_section(text, key)
    if preferred:
        value = _find_metric_in_section(preferred, patterns)
        if value is not None:
            return value
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            window = text[match.end() : match.end() + 220]
            values = _numbers_from(window)
            if values:
                return int(values[0])
    return None


def _preferred_section(text: str, key: str) -> str:
    if key in {"revenue", "net_profit", "operating_cashflow", "assets", "equity"}:
        return _section_after(text, "主要会计数据和财务指标", 4500)
    if key in {"receivables", "inventory"}:
        return _section_after(text, "资产构成重大变动情况", 4500)
    if key == "liabilities":
        return _section_after(text, "合并资产负债表", 12000) or _section_after(text, "负债合计", 3000)
    if key == "rd_expense":
        return _section_after(text, "研发投入", 5000)
    return ""


def _section_after(text: str, marker: str, max_chars: int) -> str:
    idx = text.find(marker)
    if idx == -1:
        return ""
    return text[idx : idx + max_chars]


def _find_metric_in_section(section: str, patterns: Iterable[str]) -> Optional[int]:
    scale = _section_scale(section)
    for pattern in patterns:
        match = re.search(_fuzzy_label(pattern), section)
        if not match:
            continue
        values = _numbers_from(section[match.end() : match.end() + 240])
        if values:
            return int(values[0] * scale)
    return None


def _fuzzy_label(pattern: str) -> str:
    if pattern.startswith("(?"):
        return pattern
    return r"\s*".join(map(re.escape, pattern))


def _numbers_from(text: str) -> List[float]:
    values = []
    for raw in re.findall(r"[-+]?\d[\d,，]*(?:\.\d+)?", text):
        cleaned = raw.replace(",", "").replace("，", "")
        try:
            values.append(float(cleaned))
        except ValueError:
            continue
    return [value for value in values if abs(value) > 10]


def _section_scale(section: str) -> int:
    head = section[:500]
    if "单位：万元" in head or "单位:万元" in head:
        return 10_000
    if "单位：千元" in head or "单位:千元" in head:
        return 1_000
    return 1


def _metric(value: int, key: str, report: dict) -> dict:
    return {
        "value": value,
        "unit": "CNY",
        "concept": f"cninfo-{key}",
        "filed": report.get("publish_date"),
        "end": _period_end(report["period"]),
        "accn": report.get("announcement_id") or report["id"],
    }


def _normalize_metric_scale(metrics: dict):
    assets = metrics.get("assets", {}).get("value")
    revenue = metrics.get("revenue", {}).get("value")
    if assets is not None and assets < 10_000_000_000:
        multiplier = 1_000
    elif revenue is not None and revenue < 1_000_000_000:
        multiplier = 1_000
    else:
        multiplier = 1
    if multiplier == 1:
        return
    for metric in metrics.values():
        if metric.get("value") is not None:
            metric["value"] = int(metric["value"] * multiplier)


def _normalize_balance_sheet_scale(metrics: dict):
    assets = metrics.get("assets", {}).get("value")
    if not assets:
        return
    limits = {"liabilities": assets * 1.2, "equity": assets * 1.2, "receivables": assets, "inventory": assets}
    for key, limit in limits.items():
        value = metrics.get(key, {}).get("value")
        while value is not None and value > limit and value % 1000 == 0:
            value = value // 1000
            metrics[key]["value"] = value


def _normalize_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("\u3000", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n+", "\n", text)


def _clean_title(title: str) -> str:
    return re.sub(r"<[^>]+>", "", title or "").replace("：", "")


def _unique_periods(reports: List[dict]) -> List[dict]:
    seen = set()
    result = []
    for report in reports:
        if report["period"] in seen:
            continue
        seen.add(report["period"])
        result.append(report)
    return result


def _date_from_millis(value) -> Optional[str]:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return None


def _period_end(period: str) -> str:
    year, fp = period.split("-")
    return {
        "FY": f"{year}-12-31",
        "Q1": f"{year}-03-31",
        "Q2": f"{year}-06-30",
        "Q3": f"{year}-09-30",
    }.get(fp, f"{year}-12-31")
