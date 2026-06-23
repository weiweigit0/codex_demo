from __future__ import annotations

import json
from typing import Optional

from backend.data_platform.repository import utc_now


class ThreeMinuteSummaryRepository:
    """Private persistence for summaries; shared knowledge remains read-only."""

    def __init__(self, store):
        self.store = store
        with self.store.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS three_minute_summaries (
                    summary_id TEXT PRIMARY KEY,
                    company_id TEXT NOT NULL,
                    input_fingerprint TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_three_minute_summary_company
                    ON three_minute_summaries(company_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS three_minute_questions (
                    question_id TEXT PRIMARY KEY,
                    summary_id TEXT NOT NULL,
                    question TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS three_minute_video_scripts (
                    script_id TEXT PRIMARY KEY,
                    summary_id TEXT NOT NULL,
                    input_fingerprint TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS three_minute_search_sources (
                    source_id TEXT PRIMARY KEY,
                    company_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def get_summary_by_fingerprint(self, fingerprint: str) -> Optional[dict]:
        with self.store.connect() as db:
            row = db.execute(
                "SELECT payload_json FROM three_minute_summaries WHERE input_fingerprint = ? AND status = 'COMPLETED'",
                (fingerprint,),
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def save_summary(self, summary: dict, fingerprint: str, status: str = "COMPLETED") -> None:
        now = utc_now()
        with self.store.connect() as db:
            db.execute(
                """INSERT INTO three_minute_summaries(summary_id, company_id, input_fingerprint, payload_json, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(summary_id) DO UPDATE SET payload_json=excluded.payload_json,
                     status=excluded.status, updated_at=excluded.updated_at""",
                (summary["summary_id"], summary["company"]["id"], fingerprint,
                 json.dumps(summary, ensure_ascii=False), status, now, now),
            )

    def get_summary(self, summary_id: str) -> Optional[dict]:
        with self.store.connect() as db:
            row = db.execute("SELECT payload_json FROM three_minute_summaries WHERE summary_id = ?", (summary_id,)).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def save_question(self, question_id: str, summary_id: str, question: str, payload: dict) -> None:
        with self.store.connect() as db:
            db.execute(
                "INSERT INTO three_minute_questions(question_id, summary_id, question, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (question_id, summary_id, question, json.dumps(payload, ensure_ascii=False), utc_now()),
            )

    def get_video_by_fingerprint(self, fingerprint: str) -> Optional[dict]:
        with self.store.connect() as db:
            row = db.execute("SELECT payload_json FROM three_minute_video_scripts WHERE input_fingerprint = ? AND status = 'COMPLETED'", (fingerprint,)).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def save_video(self, script: dict, fingerprint: str, status: str = "COMPLETED") -> None:
        now = utc_now()
        with self.store.connect() as db:
            db.execute(
                """INSERT INTO three_minute_video_scripts(script_id, summary_id, input_fingerprint, payload_json, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(script_id) DO UPDATE SET payload_json=excluded.payload_json, status=excluded.status, updated_at=excluded.updated_at""",
                (script["script_id"], script["summary_id"], fingerprint, json.dumps(script, ensure_ascii=False), status, now, now),
            )

    def get_video(self, script_id: str) -> Optional[dict]:
        with self.store.connect() as db:
            row = db.execute("SELECT payload_json FROM three_minute_video_scripts WHERE script_id = ?", (script_id,)).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def save_search_sources(self, company_id: str, sources: list[dict]) -> None:
        now = utc_now()
        with self.store.connect() as db:
            for index, source in enumerate(sources):
                db.execute("INSERT OR REPLACE INTO three_minute_search_sources(source_id, company_id, payload_json, created_at) VALUES (?, ?, ?, ?)", ("%s:%s:%d" % (company_id, source.get("source_type", "source"), index), company_id, json.dumps(source, ensure_ascii=False), now))
