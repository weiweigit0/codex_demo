from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

from backend.data_platform.repository import utc_now


class MediaRepository:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.assets_dir = self.root / "assets"
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "media.db"
        self._init_db()

    def connect(self):
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        return db

    def _init_db(self):
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS video_briefs (
                    brief_id TEXT PRIMARY KEY, nonce TEXT NOT NULL UNIQUE, content_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL, requester_reference TEXT NOT NULL, expires_at TEXT NOT NULL,
                    imported_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS video_requests (
                    request_id TEXT PRIMARY KEY, brief_id TEXT NOT NULL, requester_reference TEXT NOT NULL,
                    access_token_hash TEXT NOT NULL, output_profile TEXT NOT NULL, status TEXT NOT NULL,
                    status_note TEXT, estimate_json TEXT NOT NULL, render_json TEXT, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, UNIQUE(brief_id, requester_reference)
                );
                CREATE TABLE IF NOT EXISTS approval_events (
                    event_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, actor TEXT NOT NULL,
                    action TEXT NOT NULL, note TEXT, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS media_assets (
                    asset_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, asset_type TEXT NOT NULL,
                    relative_path TEXT NOT NULL, mime_type TEXT NOT NULL, created_at TEXT NOT NULL
                );
                """
            )

    def import_brief(self, brief: dict) -> tuple[dict, bool]:
        with self.connect() as db:
            existing = db.execute("SELECT * FROM video_briefs WHERE brief_id = ?", (brief["brief_id"],)).fetchone()
            if existing:
                return _brief_row(existing), False
            db.execute(
                "INSERT INTO video_briefs VALUES (?, ?, ?, ?, ?, ?, ?)",
                (brief["brief_id"], brief["nonce"], brief["content_hash"], json.dumps(brief, ensure_ascii=False),
                 brief["requester_reference"], brief["expires_at"], utc_now()),
            )
        return brief, True

    def get_brief(self, brief_id: str) -> Optional[dict]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM video_briefs WHERE brief_id = ?", (brief_id,)).fetchone()
        return _brief_row(row) if row else None

    def create_request(self, item: dict) -> dict:
        with self.connect() as db:
            db.execute(
                "INSERT INTO video_requests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (item["request_id"], item["brief_id"], item["requester_reference"], item["access_token_hash"],
                 item["output_profile"], item["status"], item.get("status_note"),
                 json.dumps(item["estimate"], ensure_ascii=False), json.dumps(item.get("render", {}), ensure_ascii=False),
                 item["created_at"], item["updated_at"]),
            )
        return item

    def get_request(self, request_id: str) -> Optional[dict]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM video_requests WHERE request_id = ?", (request_id,)).fetchone()
        return _request_row(row) if row else None

    def get_request_for_brief(self, brief_id: str, requester_reference: str) -> Optional[dict]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM video_requests WHERE brief_id = ? AND requester_reference = ?", (brief_id, requester_reference)).fetchone()
        return _request_row(row) if row else None

    def get_request_for_content_hash(self, content_hash: str, requester_reference: str) -> Optional[dict]:
        with self.connect() as db:
            row = db.execute(
                """SELECT requests.* FROM video_requests AS requests
                   JOIN video_briefs AS briefs ON briefs.brief_id = requests.brief_id
                   WHERE briefs.content_hash = ? AND requests.requester_reference = ?
                   ORDER BY requests.created_at DESC LIMIT 1""",
                (content_hash, requester_reference),
            ).fetchone()
        return _request_row(row) if row else None

    def update_request(self, request_id: str, **changes) -> Optional[dict]:
        current = self.get_request(request_id)
        if not current:
            return None
        current.update(changes)
        current["updated_at"] = utc_now()
        with self.connect() as db:
            db.execute(
                "UPDATE video_requests SET output_profile=?, status=?, status_note=?, estimate_json=?, render_json=?, updated_at=? WHERE request_id=?",
                (current["output_profile"], current["status"], current.get("status_note"),
                 json.dumps(current["estimate"], ensure_ascii=False), json.dumps(current.get("render", {}), ensure_ascii=False),
                 current["updated_at"], request_id),
            )
        return current

    def add_event(self, event: dict) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO approval_events VALUES (?, ?, ?, ?, ?, ?)", (event["event_id"], event["request_id"], event["actor"], event["action"], event.get("note"), event["created_at"]))

    def events(self, request_id: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM approval_events WHERE request_id = ? ORDER BY created_at", (request_id,)).fetchall()
        return [dict(row) for row in rows]

    def pending_requests(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM video_requests WHERE status IN ('PENDING_REVIEW', 'QUEUED', 'FAILED') ORDER BY updated_at", ()).fetchall()
        return [_request_row(row) for row in rows]

    def queued_requests(self, limit: int = 5) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM video_requests WHERE status = 'QUEUED' ORDER BY created_at LIMIT ?", (limit,)).fetchall()
        return [_request_row(row) for row in rows]

    def claim_request(self, request_id: str) -> Optional[dict]:
        """Atomically claim one queued request so multiple workers do not double bill."""
        with self.connect() as db:
            cursor = db.execute("UPDATE video_requests SET status = 'AUDIO_RENDERING', status_note = ?, updated_at = ? WHERE request_id = ? AND status = 'QUEUED'", ("独立媒体 Worker 正在生成配音。", utc_now(), request_id))
            if cursor.rowcount != 1:
                return None
        return self.get_request(request_id)

    def add_asset(self, asset: dict) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO media_assets VALUES (?, ?, ?, ?, ?, ?)", (asset["asset_id"], asset["request_id"], asset["asset_type"], asset["relative_path"], asset["mime_type"], asset["created_at"]))

    def assets(self, request_id: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM media_assets WHERE request_id = ? ORDER BY created_at", (request_id,)).fetchall()
        return [dict(row) for row in rows]


def _brief_row(row):
    return json.loads(row["payload_json"])


def _request_row(row):
    item = dict(row)
    item["estimate"] = json.loads(item.pop("estimate_json"))
    item["render"] = json.loads(item.pop("render_json") or "{}")
    return item
