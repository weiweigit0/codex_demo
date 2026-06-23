from __future__ import annotations

import json
from typing import Optional

from backend.data_platform.repository import utc_now
from backend.repositories.sqlite_store import SQLiteStore


class KnowledgeRepository:
    """Normalized, evidence-first local knowledge store.

    Source document metadata remains in DataRepository for backwards compatibility;
    this repository contains the queryable canonical representation used by domains.
    """

    def __init__(self, store: SQLiteStore):
        self.store = store
        self._init_db()

    def _init_db(self) -> None:
        with self.store.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS canonical_documents (
                    document_id TEXT PRIMARY KEY,
                    company_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_authority TEXT NOT NULL,
                    report_period TEXT,
                    source_url TEXT,
                    content_hash TEXT,
                    language TEXT NOT NULL DEFAULT 'zh',
                    version INTEGER NOT NULL DEFAULT 1,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_canonical_documents_company ON canonical_documents(company_id, source_type, report_period);
                CREATE TABLE IF NOT EXISTS document_pages (
                    document_id TEXT NOT NULL,
                    page_number INTEGER NOT NULL,
                    text_content TEXT NOT NULL,
                    image_path TEXT,
                    parse_method TEXT NOT NULL,
                    quality_status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    PRIMARY KEY(document_id, page_number)
                );
                CREATE TABLE IF NOT EXISTS document_blocks (
                    block_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    company_id TEXT NOT NULL,
                    page_number INTEGER,
                    section_title TEXT,
                    content_type TEXT NOT NULL,
                    text_content TEXT NOT NULL,
                    table_json TEXT,
                    bbox_json TEXT,
                    source_quote TEXT,
                    quality_status TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_document_blocks_document ON document_blocks(document_id, page_number);
                CREATE INDEX IF NOT EXISTS idx_document_blocks_company ON document_blocks(company_id, section_title);
                CREATE TABLE IF NOT EXISTS financial_facts (
                    fact_id TEXT PRIMARY KEY,
                    company_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    period TEXT NOT NULL,
                    metric_key TEXT NOT NULL,
                    value REAL,
                    unit TEXT,
                    source_block_id TEXT,
                    page_number INTEGER,
                    table_name TEXT,
                    row_label TEXT,
                    column_label TEXT,
                    quality_status TEXT NOT NULL,
                    parser_version TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(company_id, period, metric_key, document_id)
                );
                CREATE INDEX IF NOT EXISTS idx_financial_facts_company ON financial_facts(company_id, period, metric_key);
                CREATE TABLE IF NOT EXISTS company_facts (
                    fact_id TEXT PRIMARY KEY,
                    company_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    claim TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    source_block_ids_json TEXT NOT NULL,
                    source_authority TEXT NOT NULL,
                    quality_status TEXT NOT NULL,
                    extractor_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_company_facts_company ON company_facts(company_id, category);
                CREATE TABLE IF NOT EXISTS model_runs (
                    run_id TEXT PRIMARY KEY,
                    company_id TEXT,
                    run_type TEXT NOT NULL,
                    input_fingerprint TEXT NOT NULL,
                    model_provider TEXT,
                    model_name TEXT,
                    prompt_version TEXT,
                    status TEXT NOT NULL,
                    output_json TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_model_runs_fingerprint ON model_runs(run_type, input_fingerprint, status);
                CREATE TABLE IF NOT EXISTS financial_agent_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    company_id TEXT NOT NULL,
                    analysis_id TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    evidence_ids_json TEXT NOT NULL,
                    generation_meta_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_financial_agent_artifacts_company
                    ON financial_agent_artifacts(company_id, artifact_type, created_at DESC);
                """
            )

    def upsert_document(self, document: dict, authority: str) -> None:
        now = utc_now()
        metadata = dict(document)
        with self.store.connect() as db:
            db.execute(
                """INSERT INTO canonical_documents(document_id, company_id, source_type, source_authority, report_period, source_url, content_hash, metadata_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(document_id) DO UPDATE SET source_type=excluded.source_type,
                     source_authority=excluded.source_authority, report_period=excluded.report_period,
                     source_url=excluded.source_url, content_hash=COALESCE(excluded.content_hash, canonical_documents.content_hash),
                     metadata_json=excluded.metadata_json, version=canonical_documents.version + 1, updated_at=excluded.updated_at""",
                (document["id"], document["company_id"], document.get("report_type", "unknown"), authority,
                 document.get("period"), document.get("source_url"), document.get("content_hash"),
                 json.dumps(metadata, ensure_ascii=False), now, now),
            )

    def replace_pages_and_blocks(self, document: dict, pages: list[dict], blocks: list[dict]) -> None:
        now = utc_now()
        with self.store.connect() as db:
            db.execute("DELETE FROM document_pages WHERE document_id = ?", (document["id"],))
            db.execute("DELETE FROM document_blocks WHERE document_id = ?", (document["id"],))
            for page in pages:
                db.execute(
                    """INSERT INTO document_pages(document_id, page_number, text_content, image_path, parse_method, quality_status, metadata_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (document["id"], page["page_number"], page.get("text", ""), page.get("image_path"),
                     page.get("parse_method", "native_text"), page.get("quality_status", "extracted"),
                    json.dumps(page.get("metadata", {}), ensure_ascii=False)),
                )
            for block in blocks:
                db.execute(
                    """INSERT INTO document_blocks(block_id, document_id, company_id, page_number, section_title, content_type, text_content, table_json, bbox_json, source_quote, quality_status, confidence, metadata_json, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (block["block_id"], document["id"], document["company_id"], block.get("page_number"),
                     block.get("section_title"), block.get("content_type", "paragraph"), block.get("text", ""),
                     _json_or_none(block.get("table")), _json_or_none(block.get("bbox")), block.get("source_quote"),
                     block.get("quality_status", "extracted"), block.get("confidence", "medium"),
                     json.dumps(block.get("metadata", {}), ensure_ascii=False), now),
                )

    def list_documents(self, company_id: str, source_type: str = "", limit: int = 50) -> list[dict]:
        sql = "SELECT * FROM canonical_documents WHERE company_id = ?"
        params: list = [company_id]
        if source_type:
            sql += " AND source_type = ?"
            params.append(source_type)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self.store.connect() as db:
            rows = db.execute(sql, tuple(params)).fetchall()
        return [_document_payload(dict(row)) for row in rows]
    def replace_financial_facts(self, company_id: str, document_id: str, period: str, facts: list[dict]) -> None:
        now = utc_now()
        with self.store.connect() as db:
            db.execute("DELETE FROM financial_facts WHERE company_id = ? AND document_id = ? AND period = ?", (company_id, document_id, period))
            for fact in facts:
                db.execute(
                    """INSERT INTO financial_facts(fact_id, company_id, document_id, period, metric_key, value, unit, source_block_id, page_number, table_name, row_label, column_label, quality_status, parser_version, payload_json, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (fact["fact_id"], company_id, document_id, period, fact["metric_key"], _db_number(fact.get("value")), fact.get("unit"),
                     fact.get("source_block_id"), fact.get("page_number"), fact.get("table_name"), fact.get("row_label"),
                     fact.get("column_label"), fact.get("quality_status", "needs_review"), fact.get("parser_version", "knowledge_v1"),
                     json.dumps(fact, ensure_ascii=False), now, now),
                )

    def list_financial_facts(self, company_id: str, periods: Optional[list[str]] = None, validated_only: bool = False) -> list[dict]:
        sql = "SELECT payload_json FROM financial_facts WHERE company_id = ?"
        params: list = [company_id]
        if periods:
            sql += " AND period IN (%s)" % ",".join("?" for _ in periods)
            params.extend(periods)
        if validated_only:
            sql += " AND quality_status = 'validated'"
        sql += " ORDER BY period DESC, metric_key"
        with self.store.connect() as db:
            rows = db.execute(sql, tuple(params)).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def list_blocks(self, company_id: str, query: str = "", limit: int = 20) -> list[dict]:
        sql = "SELECT * FROM document_blocks WHERE company_id = ?"
        params: list = [company_id]
        if query:
            sql += " AND text_content LIKE ?"
            params.append("%%%s%%" % query)
        sql += " ORDER BY document_id DESC, page_number ASC LIMIT ?"
        params.append(limit)
        with self.store.connect() as db:
            rows = db.execute(sql, tuple(params)).fetchall()
        return [_block_payload(dict(row)) for row in rows]

    def list_document_blocks(self, document_id: str) -> list[dict]:
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT * FROM document_blocks WHERE document_id = ? ORDER BY page_number, block_id",
                (document_id,),
            ).fetchall()
        return [_block_payload(dict(row)) for row in rows]

    def get_block(self, block_id: str) -> Optional[dict]:
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM document_blocks WHERE block_id = ?", (block_id,)).fetchone()
        return _block_payload(dict(row)) if row else None

    def upsert_company_facts(self, company_id: str, facts: list[dict]) -> None:
        now = utc_now()
        with self.store.connect() as db:
            for fact in facts:
                db.execute(
                    """INSERT INTO company_facts(fact_id, company_id, category, claim, value_json, source_block_ids_json, source_authority, quality_status, extractor_version, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(fact_id) DO UPDATE SET claim=excluded.claim, value_json=excluded.value_json,
                         source_block_ids_json=excluded.source_block_ids_json, quality_status=excluded.quality_status,
                         extractor_version=excluded.extractor_version, updated_at=excluded.updated_at""",
                    (fact["fact_id"], company_id, fact["category"], fact["claim"], json.dumps(fact.get("value", {}), ensure_ascii=False),
                     json.dumps(fact.get("source_block_ids", []), ensure_ascii=False), fact.get("source_authority", "official_filing"),
                     fact.get("quality_status", "extracted"), fact.get("extractor_version", "agent_v1"), now, now),
                )

    def list_company_facts(self, company_id: str, category: str = "", limit: int = 100) -> list[dict]:
        sql = "SELECT * FROM company_facts WHERE company_id = ?"
        params: list = [company_id]
        if category:
            sql += " AND category = ?"
            params.append(category)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self.store.connect() as db:
            rows = db.execute(sql, tuple(params)).fetchall()
        return [{
            "fact_id": row["fact_id"], "category": row["category"], "claim": row["claim"],
            "value": json.loads(row["value_json"]), "source_block_ids": json.loads(row["source_block_ids_json"]),
            "source_authority": row["source_authority"], "quality_status": row["quality_status"],
            "extractor_version": row["extractor_version"], "updated_at": row["updated_at"],
        } for row in rows]

    def get_completed_model_run(self, run_type: str, input_fingerprint: str) -> Optional[dict]:
        with self.store.connect() as db:
            row = db.execute(
                """SELECT * FROM model_runs WHERE run_type = ? AND input_fingerprint = ? AND status = 'COMPLETED'
                   ORDER BY completed_at DESC LIMIT 1""",
                (run_type, input_fingerprint),
            ).fetchone()
        return _model_run_payload(dict(row)) if row else None

    def start_model_run(self, run: dict) -> None:
        with self.store.connect() as db:
            db.execute(
                """INSERT INTO model_runs(run_id, company_id, run_type, input_fingerprint, model_provider, model_name, prompt_version, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run["run_id"], run.get("company_id"), run["run_type"], run["input_fingerprint"],
                 run.get("model_provider"), run.get("model_name"), run.get("prompt_version"), run["status"], run["created_at"]),
            )

    def finish_model_run(self, run_id: str, status: str, output: Optional[dict] = None, error_message: str = "") -> None:
        with self.store.connect() as db:
            db.execute(
                """UPDATE model_runs SET status = ?, output_json = ?, error_message = ?, completed_at = ? WHERE run_id = ?""",
                (status, json.dumps(output, ensure_ascii=False) if output is not None else None, error_message[:500] or None, utc_now(), run_id),
            )

    def replace_financial_agent_artifacts(self, company_id: str, analysis_id: str, result: dict) -> None:
        """Persist agent output in queryable, evidence-linked records."""
        now = utc_now()
        artifacts = []
        for index, item in enumerate(result.get("observations", [])):
            artifacts.append(("observation", "observation_%d" % index, item, item.get("evidence_block_ids", [])))
        for item in result.get("risk_facts", []):
            artifacts.append(("risk_fact", item.get("fact_id") or "risk_fact", item, item.get("evidence_block_ids", [])))
        for index, item in enumerate(result.get("risk_assessments", [])):
            artifacts.append(("risk_assessment", "risk_assessment_%d" % index, item, item.get("evidence_fact_ids", [])))
        with self.store.connect() as db:
            db.execute("DELETE FROM financial_agent_artifacts WHERE analysis_id = ?", (analysis_id,))
            for artifact_type, suffix, payload, evidence_ids in artifacts:
                db.execute(
                    """INSERT INTO financial_agent_artifacts(artifact_id, company_id, analysis_id, artifact_type, payload_json, evidence_ids_json, generation_meta_json, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    ("%s:%s" % (analysis_id, suffix), company_id, analysis_id, artifact_type,
                     json.dumps(payload, ensure_ascii=False), json.dumps(evidence_ids, ensure_ascii=False),
                    json.dumps(result.get("generation_meta", {}), ensure_ascii=False), now),
                )

    def list_financial_agent_artifacts(self, company_id: str, limit: int = 80) -> list[dict]:
        with self.store.connect() as db:
            rows = db.execute(
                """SELECT * FROM financial_agent_artifacts WHERE company_id = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (company_id, limit),
            ).fetchall()
        return [{
            "artifact_id": row["artifact_id"], "analysis_id": row["analysis_id"],
            "artifact_type": row["artifact_type"], "payload": json.loads(row["payload_json"]),
            "evidence_ids": json.loads(row["evidence_ids_json"]),
            "generation_meta": json.loads(row["generation_meta_json"]), "created_at": row["created_at"],
        } for row in rows]


def _json_or_none(value):
    return json.dumps(value, ensure_ascii=False) if value is not None else None


def _db_number(value):
    """SQLite INTEGER overflows on malformed PDF-extracted values; retain raw JSON separately."""
    return float(value) if isinstance(value, (int, float)) else None


def _block_payload(row: dict) -> dict:
    return {
        "block_id": row["block_id"], "document_id": row["document_id"], "company_id": row["company_id"],
        "page_number": row["page_number"], "section_title": row["section_title"], "content_type": row["content_type"],
        "text": row["text_content"], "table": json.loads(row["table_json"]) if row.get("table_json") else None,
        "bbox": json.loads(row["bbox_json"]) if row.get("bbox_json") else None, "source_quote": row["source_quote"],
        "quality_status": row["quality_status"], "confidence": row["confidence"],
        "metadata": json.loads(row["metadata_json"]),
    }


def _document_payload(row: dict) -> dict:
    return {
        "document_id": row["document_id"], "company_id": row["company_id"], "source_type": row["source_type"],
        "source_authority": row["source_authority"], "report_period": row["report_period"], "source_url": row["source_url"],
        "content_hash": row["content_hash"], "language": row["language"], "version": row["version"],
        "metadata": json.loads(row["metadata_json"]), "updated_at": row["updated_at"],
    }


def _model_run_payload(row: dict) -> dict:
    return {
        "run_id": row["run_id"], "company_id": row["company_id"], "run_type": row["run_type"],
        "input_fingerprint": row["input_fingerprint"], "model_provider": row["model_provider"],
        "model_name": row["model_name"], "prompt_version": row["prompt_version"], "status": row["status"],
        "output": json.loads(row["output_json"]) if row.get("output_json") else None,
        "error_message": row["error_message"], "created_at": row["created_at"], "completed_at": row["completed_at"],
    }
