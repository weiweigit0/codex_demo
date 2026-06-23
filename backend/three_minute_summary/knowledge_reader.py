from __future__ import annotations

from backend.data_platform.repository import json_hash
from backend.three_minute_summary.search_enricher import ControlledSearchEnricher


class SummaryKnowledgeReader:
    """Read-only adapter over the shared normalized knowledge layer."""

    def __init__(self, data_service):
        self.data_service = data_service
        self.enricher = ControlledSearchEnricher(data_service)

    def build_context(self, ticker: str, market: str, period_type: str, period: str | None, allow_web_enrichment: bool = False) -> dict:
        company = self.data_service.resolve_company(ticker, market)
        options = self.data_service.list_report_options(company)
        available = options.get("annual" if period_type == "annual" else "quarterly", [])
        selected_period = period or (available[0] if available else None)
        if not selected_period:
            raise ValueError("没有可用于三分钟总结的完整报告期。")
        dataset = self.data_service.get_financial_dataset(company, periods=[selected_period], period_type=period_type)
        facts = [item for item in self.data_service.knowledge_financial_facts(company, [selected_period]) if item.get("quality_status") == "validated"]
        documents = [item for item in self.data_service.list_profile_documents(company) if item.get("period") == selected_period]
        if not documents:
            documents = [
                item for item in self.data_service.repository.list_documents(company["id"], {"annual", "quarterly"})
                if item.get("period") == selected_period
            ]
        blocks = []
        for document in documents[:1]:
            blocks.extend(self.data_service.canonical_document_blocks(document)[:48])
        if not blocks:
            blocks = self.data_service.knowledge_blocks(company, "", 36)
        company_facts = self.data_service.knowledge.list_company_facts(company["id"], limit=20)
        financial_artifacts = self.data_service.knowledge.list_financial_agent_artifacts(company["id"], limit=40)
        external_sources = []
        if allow_web_enrichment and not company_facts:
            enrichment = self.enricher.enrich(company)
            external_sources = enrichment.get("sources", [])
            blocks.extend(enrichment.get("blocks", []))
        context = {
            "company": company, "period": selected_period, "period_type": period_type,
            "financial_dataset": dataset, "validated_financial_facts": facts,
            "filing_evidence_blocks": blocks, "company_profile_facts": company_facts,
            "financial_agent_artifacts": financial_artifacts,
            "external_sources": external_sources,
            "coverage": {"financial": bool(facts), "filing": bool(blocks), "company_profile": bool(company_facts)},
        }
        context["fingerprint"] = json_hash(_fingerprint_payload(context))
        return context


def _fingerprint_payload(context: dict) -> dict:
    return {
        "company": context["company"]["id"], "period": context["period"],
        "facts": context["validated_financial_facts"],
        "blocks": [{"id": item.get("block_id"), "text": item.get("text", "")} for item in context["filing_evidence_blocks"]],
        "profile": context["company_profile_facts"], "financial_agent": context["financial_agent_artifacts"],
        "external_sources": context["external_sources"],
    }
