from __future__ import annotations

from typing import List, Optional

from backend.data_platform.service import DataService


class ReportService:
    """Financial-report facade. External source calls are owned by DataService."""

    def __init__(self, data_service: DataService):
        self.data_service = data_service

    def list_options(self, company: dict) -> dict:
        return self.data_service.list_report_options(company)

    def fetch_financial_dataset(
        self,
        company: dict,
        periods: Optional[List[str]] = None,
        period_type: str = "annual",
    ) -> dict:
        return self.data_service.get_financial_dataset(company, periods=periods, period_type=period_type)

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
