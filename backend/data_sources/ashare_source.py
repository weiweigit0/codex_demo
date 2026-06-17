from __future__ import annotations

from typing import List

from backend.data_sources.ashare_index import AShareIndex
from backend.data_sources.cninfo_client import CninfoClient


class AShareSource:
    def __init__(self):
        self.index = AShareIndex()
        self.cninfo = CninfoClient()

    def search_companies(self, query: str) -> List[dict]:
        return self.index.search(query, limit=20)

    def resolve_company(self, ticker_or_name: str) -> dict:
        return self.index.resolve(ticker_or_name)

    def top_companies(self, limit: int = 80) -> List[dict]:
        return self.index.top(limit=limit)

    def coverage(self) -> dict:
        return self.index.coverage()

    def list_reports(self, company: dict) -> List[dict]:
        return self.cninfo.list_reports(company)

    def fetch_financial_dataset(self, company: dict, periods=None, period_type: str = "annual") -> dict:
        return self.cninfo.fetch_financial_dataset(company, periods=periods, period_type=period_type)
