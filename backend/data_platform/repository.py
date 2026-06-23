from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

from backend.repositories.sqlite_store import SQLiteStore


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class DataRepository:
    """Versioned metadata repository. Binary/text assets live in the assets directory."""

    def __init__(self, store: SQLiteStore):
        self.store = store
        self._init_db()

    def _init_db(self) -> None:
        with self.store.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS data_companies (
                    company_id TEXT PRIMARY KEY,
                    market TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    source TEXT,
                    updated_at TEXT NOT NULL,
                    UNIQUE(market, ticker)
                );
                CREATE TABLE IF NOT EXISTS source_documents (
                    document_id TEXT PRIMARY KEY,
                    company_id TEXT NOT NULL,
                    report_type TEXT NOT NULL,
                    period TEXT NOT NULL,
                    source_url TEXT,
                    metadata_json TEXT NOT NULL,
                    content_hash TEXT,
                    fetched_at TEXT NOT NULL,
                    expires_at TEXT,
                    UNIQUE(company_id, report_type, period, source_url)
                );
                CREATE TABLE IF NOT EXISTS data_snapshots (
                    resource_type TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    company_id TEXT,
                    payload_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    source_version TEXT,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT,
                    PRIMARY KEY(resource_type, cache_key)
                );
                CREATE INDEX IF NOT EXISTS idx_data_snapshots_company ON data_snapshots(company_id, resource_type);
                CREATE TABLE IF NOT EXISTS refresh_jobs (
                    job_id TEXT PRIMARY KEY,
                    resource_type TEXT NOT NULL,
                    company_id TEXT,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_refresh_jobs_company ON refresh_jobs(company_id, created_at DESC);
                """
            )

    def upsert_company(self, company: dict) -> dict:
        now = utc_now()
        with self.store.connect() as db:
            db.execute(
                """INSERT INTO data_companies(company_id, market, ticker, payload_json, source, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(company_id) DO UPDATE SET
                     market=excluded.market, ticker=excluded.ticker, payload_json=excluded.payload_json,
                     source=excluded.source, updated_at=excluded.updated_at""",
                (company["id"], company["market"], company["ticker"], json.dumps(company, ensure_ascii=False), company.get("source"), now),
            )
        return company

    def get_company(self, ticker: str, market: str) -> Optional[dict]:
        with self.store.connect() as db:
            row = db.execute(
                "SELECT payload_json FROM data_companies WHERE market = ? AND upper(ticker) = upper(?)",
                (market, ticker),
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def search_companies(self, query: str, market: str, limit: int = 20) -> list[dict]:
        if not query:
            return []
        marker = f"%{query.lower()}%"
        sql = "SELECT payload_json FROM data_companies WHERE (lower(ticker) LIKE ? OR lower(payload_json) LIKE ?)"
        params: list[Any] = [marker, marker]
        if market != "ALL":
            sql += " AND market = ?"
            params.append(market)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self.store.connect() as db:
            rows = db.execute(sql, tuple(params)).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def upsert_document(self, document: dict, expires_at: Optional[str] = None) -> dict:
        now = utc_now()
        # Financial analysis and company-profile collection can discover the same
        # official filing through different adapters. The source identity wins over
        # the caller-generated ID so both domains share one persisted document.
        if document.get("source_url"):
            with self.store.connect() as db:
                existing = db.execute(
                    """SELECT document_id FROM source_documents
                       WHERE company_id = ? AND report_type = ? AND period = ? AND source_url = ?""",
                    (document["company_id"], document["report_type"], document["period"], document["source_url"]),
                ).fetchone()
            if existing:
                document["id"] = existing["document_id"]
        metadata = dict(document)
        with self.store.connect() as db:
            db.execute(
                """INSERT INTO source_documents(document_id, company_id, report_type, period, source_url, metadata_json, content_hash, fetched_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(document_id) DO UPDATE SET metadata_json=excluded.metadata_json,
                     source_url=excluded.source_url, content_hash=COALESCE(excluded.content_hash, source_documents.content_hash),
                     fetched_at=excluded.fetched_at, expires_at=excluded.expires_at""",
                (document["id"], document["company_id"], document["report_type"], document["period"], document.get("source_url"),
                 json.dumps(metadata, ensure_ascii=False), document.get("content_hash"), now, expires_at),
            )
        return document

    def list_documents(self, company_id: str, report_types: Optional[set[str]] = None) -> list[dict]:
        sql = "SELECT metadata_json, content_hash FROM source_documents WHERE company_id = ?"
        params: list[Any] = [company_id]
        if report_types:
            placeholders = ",".join("?" for _ in report_types)
            sql += f" AND report_type IN ({placeholders})"
            params.extend(sorted(report_types))
        sql += " ORDER BY period DESC, fetched_at DESC"
        with self.store.connect() as db:
            rows = db.execute(sql, tuple(params)).fetchall()
        result = []
        for row in rows:
            item = json.loads(row["metadata_json"])
            if row["content_hash"]:
                item["content_hash"] = row["content_hash"]
            result.append(item)
        return result

    def get_snapshot(self, resource_type: str, cache_key: str, allow_stale: bool = True) -> Optional[dict]:
        with self.store.connect() as db:
            row = db.execute(
                "SELECT * FROM data_snapshots WHERE resource_type = ? AND cache_key = ?",
                (resource_type, cache_key),
            ).fetchone()
        if not row:
            return None
        data = dict(row)
        data["payload"] = json.loads(data.pop("payload_json"))
        if not allow_stale and data.get("expires_at") and data["expires_at"] <= utc_now():
            return None
        data["is_stale"] = bool(data.get("expires_at") and data["expires_at"] <= utc_now())
        return data

    def save_snapshot(
        self,
        resource_type: str,
        cache_key: str,
        payload: dict,
        company_id: Optional[str] = None,
        source_version: Optional[str] = None,
        expires_at: Optional[str] = None,
    ) -> dict:
        now = utc_now()
        content_hash = json_hash(payload)
        with self.store.connect() as db:
            db.execute(
                """INSERT INTO data_snapshots(resource_type, cache_key, company_id, payload_json, content_hash, source_version, updated_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(resource_type, cache_key) DO UPDATE SET company_id=excluded.company_id,
                     payload_json=excluded.payload_json, content_hash=excluded.content_hash, source_version=excluded.source_version,
                     updated_at=excluded.updated_at, expires_at=excluded.expires_at""",
                (resource_type, cache_key, company_id, json.dumps(payload, ensure_ascii=False), content_hash, source_version, now, expires_at),
            )
        return {"payload": payload, "content_hash": content_hash, "updated_at": now, "expires_at": expires_at}

    def delete_snapshots(self, resource_type: str, company_id: Optional[str] = None) -> int:
        sql = "DELETE FROM data_snapshots WHERE resource_type = ?"
        params: list[Any] = [resource_type]
        if company_id:
            sql += " AND company_id = ?"
            params.append(company_id)
        with self.store.connect() as db:
            cursor = db.execute(sql, tuple(params))
            return cursor.rowcount

    def create_job(self, job: dict) -> dict:
        with self.store.connect() as db:
            db.execute(
                """INSERT INTO refresh_jobs(job_id, resource_type, company_id, payload_json, status, progress, error_message, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (job["job_id"], job["resource_type"], job.get("company_id"), json.dumps(job.get("payload", {}), ensure_ascii=False),
                 job["status"], job.get("progress", 0), job.get("error_message"), job["created_at"], job["updated_at"]),
            )
        return job

    def update_job(self, job_id: str, **changes: Any) -> Optional[dict]:
        current = self.get_job(job_id)
        if not current:
            return None
        current.update(changes)
        current["updated_at"] = utc_now()
        with self.store.connect() as db:
            db.execute(
                """UPDATE refresh_jobs SET payload_json=?, status=?, progress=?, error_message=?, updated_at=? WHERE job_id=?""",
                (json.dumps(current.get("payload", {}), ensure_ascii=False), current["status"], current.get("progress", 0),
                 current.get("error_message"), current["updated_at"], job_id),
            )
        return current

    def get_job(self, job_id: str) -> Optional[dict]:
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM refresh_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json"))
        return item
