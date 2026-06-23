from __future__ import annotations

import time
import re
from datetime import datetime
from typing import Dict, Iterable, List, Optional

import requests


SEC_HEADERS = {
    "User-Agent": "FinancialReportMining/0.2 contact@example.com",
    "Accept-Encoding": "gzip, deflate",
}

CONCEPTS = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "gross_profit": ["GrossProfit"],
    "net_profit": ["NetIncomeLoss", "ProfitLoss"],
    "operating_cashflow": ["NetCashProvidedByUsedInOperatingActivities"],
    "assets": ["Assets"],
    "liabilities": ["Liabilities"],
    "equity": ["StockholdersEquity"],
    "inventory": ["InventoryNet", "InventoryFinishedGoodsNetOfReserves"],
    "receivables": ["AccountsReceivableNetCurrent", "AccountsReceivableNet"],
    "operating_income": ["OperatingIncomeLoss"],
    "rd_expense": ["ResearchAndDevelopmentExpense"],
}

SUPPORTED_SEC_FORMS = {"10-K", "10-Q", "20-F", "6-K"}
PROFILE_SEC_FORMS = SUPPORTED_SEC_FORMS | {"S-1", "F-1"}
ANNUAL_SEC_FORMS = {"10-K", "20-F"}
QUARTERLY_SEC_FORMS = {"10-Q", "6-K"}


class SecClientError(RuntimeError):
    pass


class SecClient:
    def __init__(self):
        self._ticker_cache: Optional[List[dict]] = None
        self._facts_cache: Dict[str, dict] = {}
        self._submissions_cache: Dict[str, dict] = {}
        self._last_request = 0.0
        # SEC filings must not inherit an enterprise proxy configured for the LLM.
        self._http = requests.Session()
        self._http.trust_env = False

    def search_companies(self, query: str) -> List[dict]:
        query = query.strip().lower()
        if not query:
            return []
        items = self._load_company_tickers()
        matches = [
            item
            for item in items
            if query in item["ticker"].lower() or query in item["name"].lower()
        ]
        return matches[:12]

    def resolve_company(self, ticker_or_name: str) -> dict:
        query = ticker_or_name.strip().lower()
        if not query:
            raise SecClientError("请输入公司代码或名称。")
        items = self._load_company_tickers()
        exact = [item for item in items if item["ticker"].lower() == query]
        candidates = exact or [
            item
            for item in items
            if query in item["ticker"].lower() or query in item["name"].lower()
        ]
        if not candidates:
            raise SecClientError(f"没有在 SEC 公司列表中找到：{ticker_or_name}")
        return candidates[0]

    def list_periods(self, cik: str) -> dict:
        facts = self.fetch_companyfacts(cik)
        records = self._collect_records(facts)
        annual = sorted(
            [key for key in records.keys() if key.endswith("-FY")],
            reverse=True,
        )
        quarters = sorted(
            [key for key in records.keys() if not key.endswith("-FY")],
            reverse=True,
        )
        return {"annual": annual[:12], "quarterly": quarters[:24]}

    def fetch_financial_dataset(self, cik: str) -> dict:
        facts = self.fetch_companyfacts(cik)
        submissions = self.fetch_submissions(cik)
        return {
            "records": self._collect_records(facts),
            "filings": self._collect_filings(submissions),
        }

    def list_filing_documents(self, cik: str) -> List[dict]:
        submissions = self.fetch_submissions(cik)
        recent = submissions.get("filings", {}).get("recent", {})
        documents = []
        for idx, form in enumerate(recent.get("form", [])):
            if form not in PROFILE_SEC_FORMS:
                continue
            accession = _safe_get(recent.get("accessionNumber", []), idx)
            primary = _safe_get(recent.get("primaryDocument", []), idx)
            if not accession or not primary:
                continue
            cik_number = int(str(submissions.get("cik", cik)))
            documents.append({
                "accession": accession,
                "form": form,
                "report_date": _safe_get(recent.get("reportDate", []), idx),
                "filing_date": _safe_get(recent.get("filingDate", []), idx),
                "url": "https://www.sec.gov/Archives/edgar/data/%s/%s/%s" % (cik_number, accession.replace("-", ""), primary),
            })
        return documents

    def extract_filing_text(self, url: str) -> str:
        """Fetch SEC filing HTML and retain readable text for the profile Agent."""
        return self.extract_filing_text_from_html(self.download_filing_html(url))

    def download_filing_html(self, url: str) -> bytes:
        """Download and preserve the official filing source before text extraction."""
        self._throttle()
        try:
            response = self._http.get(url, headers=SEC_HEADERS, timeout=30)
        except requests.RequestException as exc:
            raise SecClientError(f"联网获取 SEC 披露文件失败：{exc}")
        if response.status_code >= 400:
            raise SecClientError(f"SEC 披露文件返回 {response.status_code}：{url}")
        return response.content

    def extract_filing_text_from_html(self, content: bytes) -> str:
        text = content.decode("utf-8", errors="ignore")
        text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\\1>", " ", text)
        text = re.sub(r"(?i)</(?:p|div|h[1-6]|tr|li|section|table)\\s*>", "\\n\\n", text)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        text = re.sub(r"&nbsp;|&#160;", " ", text)
        text = re.sub(r"&amp;", "&", text)
        text = re.sub(r"[ \\t]+", " ", text)
        text = re.sub(r"\\n{3,}", "\\n\\n", text).strip()
        if len(text) < 300:
            raise SecClientError("SEC 披露文件正文过少，无法生成公司画像。")
        return text

    def fetch_companyfacts(self, cik: str) -> dict:
        normalized = cik.zfill(10)
        if normalized not in self._facts_cache:
            url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{normalized}.json"
            self._facts_cache[normalized] = self._get_json(url)
        return self._facts_cache[normalized]

    def fetch_submissions(self, cik: str) -> dict:
        normalized = cik.zfill(10)
        if normalized not in self._submissions_cache:
            url = f"https://data.sec.gov/submissions/CIK{normalized}.json"
            self._submissions_cache[normalized] = self._get_json(url)
        return self._submissions_cache[normalized]

    def _load_company_tickers(self) -> List[dict]:
        if self._ticker_cache is None:
            data = self._get_json("https://www.sec.gov/files/company_tickers.json")
            self._ticker_cache = [
                {
                    "cik": str(item["cik_str"]).zfill(10),
                    "ticker": item["ticker"],
                    "name": item["title"],
                    "market": "US",
                    "source": "SEC EDGAR",
                }
                for item in data.values()
            ]
        return self._ticker_cache

    def _get_json(self, url: str) -> dict:
        self._throttle()
        try:
            response = self._http.get(url, headers=SEC_HEADERS, timeout=20)
        except requests.RequestException as exc:
            raise SecClientError(f"联网获取 SEC 数据失败：{exc}")
        if response.status_code >= 400:
            raise SecClientError(f"SEC 数据接口返回 {response.status_code}：{url}")
        return response.json()

    def _throttle(self):
        elapsed = time.time() - self._last_request
        if elapsed < 0.12:
            time.sleep(0.12 - elapsed)
        self._last_request = time.time()

    def _collect_records(self, facts: dict) -> Dict[str, dict]:
        us_gaap = facts.get("facts", {}).get("us-gaap", {})
        records: Dict[str, dict] = {}

        for metric_key, concept_names in CONCEPTS.items():
            for concept_name in concept_names:
                concept = us_gaap.get(concept_name)
                if not concept:
                    continue
                for unit, unit_items in concept.get("units", {}).items():
                    for item in unit_items:
                        if item.get("form") not in SUPPORTED_SEC_FORMS:
                            continue
                        key = self._period_key(item)
                        if not key:
                            continue
                        if not self._period_end_matches(item):
                            continue
                        period = records.setdefault(
                            key,
                            {
                                "period": key,
                                "fy": item.get("fy"),
                                "fp": item.get("fp"),
                                "form": item.get("form"),
                                "filed": item.get("filed"),
                                "end": item.get("end"),
                                "metrics": {},
                                "sources": [],
                            },
                        )
                        current = period["metrics"].get(metric_key)
                        next_value = {
                            "value": item.get("val"),
                            "unit": unit,
                            "concept": concept_name,
                            "filed": item.get("filed"),
                            "end": item.get("end"),
                            "accn": item.get("accn"),
                        }
                        if current is None or (item.get("filed") or "") > (current.get("filed") or ""):
                            period["metrics"][metric_key] = next_value
                        if item.get("accn"):
                            period["sources"].append(item.get("accn"))

        for record in records.values():
            record["sources"] = sorted(set(record["sources"]))
        return records

    def _period_key(self, item: dict) -> Optional[str]:
        fy = item.get("fy")
        fp = item.get("fp")
        if not fy or not fp:
            return None
        if fp not in {"FY", "Q1", "Q2", "Q3", "Q4"}:
            return None
        form = item.get("form")
        if form in QUARTERLY_SEC_FORMS and fp == "FY":
            return None
        if form in ANNUAL_SEC_FORMS and fp != "FY":
            return None
        return f"{fy}-{fp}"

    def _period_end_matches(self, item: dict) -> bool:
        fy = item.get("fy")
        fp = item.get("fp")
        end = item.get("end")
        if not fy or not fp or not end:
            return False
        try:
            end_year = int(str(end)[:4])
            fy_year = int(fy)
        except ValueError:
            return False
        if fp == "FY":
            start = item.get("start")
            if start and self._days_between(start, end) < 250:
                return False
            return end_year == fy_year
        return end_year in {fy_year, fy_year - 1}

    def _days_between(self, start: str, end: str) -> int:
        try:
            start_date = datetime.strptime(start, "%Y-%m-%d")
            end_date = datetime.strptime(end, "%Y-%m-%d")
        except ValueError:
            return 999
        return (end_date - start_date).days

    def _collect_filings(self, submissions: dict) -> Dict[str, dict]:
        recent = submissions.get("filings", {}).get("recent", {})
        filings: Dict[str, dict] = {}
        forms = recent.get("form", [])
        accession_numbers = recent.get("accessionNumber", [])
        primary_documents = recent.get("primaryDocument", [])
        report_dates = recent.get("reportDate", [])
        filing_dates = recent.get("filingDate", [])
        cik = str(submissions.get("cik", "")).zfill(10)

        for idx, form in enumerate(forms):
            if form not in SUPPORTED_SEC_FORMS:
                continue
            accn = accession_numbers[idx]
            accession_path = accn.replace("-", "")
            doc = primary_documents[idx]
            url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_path}/{doc}"
            filings[accn] = {
                "form": form,
                "report_date": _safe_get(report_dates, idx),
                "filing_date": _safe_get(filing_dates, idx),
                "url": url,
            }
        return filings


def _safe_get(items: Iterable, idx: int):
    try:
        return list(items)[idx]
    except IndexError:
        return None
