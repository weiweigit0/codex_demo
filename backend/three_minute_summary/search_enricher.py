from __future__ import annotations


class ControlledSearchEnricher:
    """Use existing normalized encyclopedia adapters as a constrained web fallback."""

    def __init__(self, data_service):
        self.data_service = data_service

    def enrich(self, company: dict) -> dict:
        context = self.data_service.get_encyclopedia(company)
        if not context:
            return {"status": "unavailable", "sources": [], "blocks": []}
        source_type = context.get("source_type") or "encyclopedia"
        document_id = "ENC-%s-%s" % (company["id"], source_type)
        blocks = self.data_service.knowledge.list_document_blocks(document_id)
        source = {"source_type": source_type, "title": context.get("title") or company.get("name"), "url": context.get("url"), "authority": "encyclopedia", "allowed_usage": context.get("allowed_usage"), "summary": context.get("summary", "")[:400]}
        return {"status": "ready", "sources": [source], "blocks": blocks[:8]}
