from __future__ import annotations

import base64
import json
import os
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_payload(payload: dict[str, Any], private_key_pem: str) -> str:
    key = serialization.load_pem_private_key(private_key_pem.encode("utf-8"), password=None, backend=default_backend())
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("VIDEO_BRIEF_PRIVATE_KEY 必须是 Ed25519 私钥")
    return base64.urlsafe_b64encode(key.sign(canonical_json(payload))).decode("ascii")


def verify_payload(payload: dict[str, Any], signature: str, public_key_pem: str) -> bool:
    try:
        key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"), backend=default_backend())
        if not isinstance(key, Ed25519PublicKey):
            return False
        key.verify(base64.urlsafe_b64decode(signature.encode("ascii")), canonical_json(payload))
        return True
    except (ValueError, TypeError, InvalidSignature):
        return False


def env_multiline(name: str) -> str:
    return os.getenv(name, "").replace("\\n", "\n").strip()
