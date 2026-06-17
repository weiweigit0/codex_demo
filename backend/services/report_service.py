from __future__ import annotations

from typing import List, Optional

from backend.data_sources.ashare_source import AShareSource
from backend.data_sources.sec_source import SecClient
from backend.repositories.json_store import JsonStore


class ReportService:
    def __init__(self, store: JsonStore, sec_client: SecClient, ashare_source: AShareSource):
        self.store = store
        self.sec_client = sec_client
        self.ashare_source = ashare_source

    def list_options(self, company: dict) -> dict:
        if company["market"] == "CN":
            reports = self.ashare_source.list_reports(company)
            annual = [item["period"] for item in reports if item["report_type"] == "annual"]
            quarterly = [item["period"] for item in reports if item["report_type"] == "quarterly"]
            return {"annual": annual, "quarterly": quarterly, "reports": reports}

        dataset = self.sec_client.fetch_financial_dataset(company["cik"])
        records = dataset["records"]
        annual = sorted([key for key in records.keys() if key.endswith("-FY")], reverse=True)[:12]
        quarterly = sorted([key for key in records.keys() if not key.endswith("-FY")], reverse=True)[:24]
        periods = {"annual": annual, "quarterly": quarterly}
        return {**periods, "reports": self._sec_report_metas(company, periods, dataset)}

    def fetch_financial_dataset(
        self,
        company: dict,
        periods: Optional[List[str]] = None,
        period_type: str = "annual",
    ) -> dict:
        if company["market"] == "CN":
            return self.ashare_source.fetch_financial_dataset(company, periods=periods, period_type=period_type)
        return self.sec_client.fetch_financial_dataset(company["cik"])

    def _sec_report_metas(self, company: dict, periods: dict, dataset: dict) -> List[dict]:
        reports = []
        records = dataset.get("records", {})
        filings = dataset.get("filings", {})
        for period in periods.get("annual", []):
            source = self._source_for_period(period, records, filings)
            reports.append(
                {
                    "id": f"{company['id']}-{period}",
                    "company_id": company["id"],
                    "report_type": "annual",
                    "period": period,
                    "publish_date": source.get("filing_date"),
                    "source_url": source.get("url"),
                    "parse_status": "structured",
                }
            )
        for period in periods.get("quarterly", []):
            source = self._source_for_period(period, records, filings)
            reports.append(
                {
                    "id": f"{company['id']}-{period}",
                    "company_id": company["id"],
                    "report_type": "quarterly",
                    "period": period,
                    "publish_date": source.get("filing_date"),
                    "source_url": source.get("url"),
                    "parse_status": "structured",
                }
            )
        return reports

    def _source_for_period(self, period: str, records: dict, filings: dict) -> dict:
        source_accns = records.get(period, {}).get("sources", [])
        for accn in source_accns:
            if accn in filings:
                return filings[accn]
        return {}
