from __future__ import annotations

import os
from pathlib import Path


_LOADED = False


def load_local_env() -> None:
    global _LOADED
    if _LOADED:
        return
    _LOADED = True

    load_env_file(Path(__file__).resolve().parents[1] / ".env")


def load_env_file(env_path: Path) -> None:
    """Load an optional local environment file without overriding process env."""
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
