from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta

from backend.repositories.sqlite_store import SQLiteStore


PHONE_PATTERN = re.compile(r"^1[3-9]\d{9}$")
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_\-\u4e00-\u9fa5]{3,32}$")
SESSION_DAYS = 7


class AuthError(ValueError):
    pass


class AuthService:
    def __init__(self, store: SQLiteStore):
        self.store = store

    def register(self, username: str, password: str, phone: str) -> dict:
        username = username.strip()
        phone = phone.strip()
        self._validate_registration(username, password, phone)
        if self.store.user_by_username(username):
            raise AuthError("用户名已被注册")
        if self.store.user_by_phone(phone):
            raise AuthError("手机号已被注册")

        now = _now()
        user = self.store.create_user(username, phone, _hash_password(password), now)
        return self._issue_session(user)

    def login(self, username: str, password: str) -> dict:
        username = username.strip()
        if not username or not password:
            raise AuthError("请输入用户名和密码")
        user = self.store.user_by_username(username)
        if not user or not _verify_password(password, user["password_hash"]):
            raise AuthError("用户名或密码错误")
        return self._issue_session(user)

    def me(self, token: str) -> dict:
        if not token:
            raise AuthError("未登录")
        user = self.store.session_user(token, _now())
        if not user:
            raise AuthError("登录已过期，请重新登录")
        return _public_user(user)

    def logout(self, token: str):
        if token:
            self.store.delete_session(token)

    def _validate_registration(self, username: str, password: str, phone: str):
        if not USERNAME_PATTERN.match(username):
            raise AuthError("用户名需为 3-32 位，可包含中文、字母、数字、下划线或短横线")
        if len(password) < 6:
            raise AuthError("密码至少需要 6 位")
        if not PHONE_PATTERN.match(phone):
            raise AuthError("请输入正确的手机号")

    def _issue_session(self, user: dict) -> dict:
        token = secrets.token_urlsafe(32)
        created_at = _now()
        expires_at = (datetime.utcnow() + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds")
        self.store.create_session(token, int(user["id"]), created_at, expires_at)
        return {"token": token, "user": _public_user(user), "expires_at": expires_at}


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, salt, expected = stored.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return hmac.compare_digest(digest.hex(), expected)


def _public_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "username": user["username"],
        "phone": user["phone"],
        "created_at": user.get("created_at"),
    }


def _now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")
