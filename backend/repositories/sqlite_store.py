from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional


class SQLiteStore:
    def __init__(self, storage_dir: Path):
        storage_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = storage_dir / "app.db"
        self._init_db()

    def connect(self):
        connection = sqlite3.connect(str(self.db_path))
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self):
        with self.connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    phone TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                )
                """
            )

    def user_by_username(self, username: str) -> Optional[dict]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            return dict(row) if row else None

    def user_by_phone(self, phone: str) -> Optional[dict]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM users WHERE phone = ?", (phone,)).fetchone()
            return dict(row) if row else None

    def user_by_id(self, user_id: int) -> Optional[dict]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return dict(row) if row else None

    def create_user(self, username: str, phone: str, password_hash: str, now: str) -> dict:
        with self.connect() as db:
            cursor = db.execute(
                """
                INSERT INTO users (username, phone, password_hash, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (username, phone, password_hash, now, now),
            )
            user_id = cursor.lastrowid
        user = self.user_by_id(user_id)
        if not user:
            raise RuntimeError("用户创建失败")
        return user

    def create_session(self, token: str, user_id: int, created_at: str, expires_at: str):
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO sessions (token, user_id, created_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (token, user_id, created_at, expires_at),
            )

    def session_user(self, token: str, now: str) -> Optional[dict]:
        with self.connect() as db:
            row = db.execute(
                """
                SELECT users.* FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.token = ? AND sessions.expires_at > ?
                """,
                (token, now),
            ).fetchone()
            return dict(row) if row else None

    def delete_session(self, token: str):
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE token = ?", (token,))
