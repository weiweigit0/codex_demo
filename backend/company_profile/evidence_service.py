from __future__ import annotations

import re
import uuid
from typing import Dict, List, Optional


class EvidenceService:
    def __init__(self, store: Dict[str, dict], company: dict, document: dict, parsed: dict, document_payload_fn):
        self.store = store
        self.company = company
        self.document = document
        self.parsed = parsed
        self.document_payload_fn = document_payload_fn

    def create(self, claim_type: str, claim: str, section_key: str, keywords: List[str], confidence: str = "MEDIUM") -> str:
        block = self.find_block(keywords) or self.find_block([section_key]) or self.parsed["blocks"][0]
        evidence_id = "ev_%s" % uuid.uuid4().hex[:12]
        item = {
            "evidence_id": evidence_id,
            "company_id": self.company["id"],
            "document_id": self.document["id"],
            "claim_type": claim_type,
            "claim": claim,
            "source": self.document_payload_fn(block.get("document") or self.document),
            "location": {
                "page": block["page"],
                "section_title": block.get("section_title") or section_key,
                "text_block_id": block["id"],
            },
            "original_text": _trim(block["text"], 520),
            "confidence": confidence,
            "extraction_method": "AGENT_LLM" if confidence != "MISSING" else "MISSING",
        }
        self.store[evidence_id] = item
        return evidence_id

    def create_from_block_id(self, claim_type: str, claim: str, block_id: str, confidence: str = "MEDIUM") -> str:
        block = self.block_by_id(block_id) or self.parsed["blocks"][0]
        evidence_id = "ev_%s" % uuid.uuid4().hex[:12]
        self.store[evidence_id] = {
            "evidence_id": evidence_id,
            "company_id": self.company["id"],
            "document_id": self.document["id"],
            "claim_type": claim_type,
            "claim": claim,
            "source": self.document_payload_fn(block.get("document") or self.document),
            "location": {
                "page": block["page"],
                "section_title": block.get("section_title") or claim_type,
                "text_block_id": block["id"],
            },
            "original_text": _trim(block["text"], 520),
            "confidence": confidence,
            "extraction_method": "AGENT_LLM",
        }
        return evidence_id

    def find_block(self, keywords: List[str]) -> Optional[dict]:
        for block in self.parsed.get("blocks", []):
            if any(keyword and keyword in block.get("text", "") for keyword in keywords):
                return block
        return None

    def block_by_id(self, block_id: str) -> Optional[dict]:
        for block in self.parsed.get("blocks", []):
            if block.get("id") == block_id:
                return block
        return None


def _trim(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "..."
