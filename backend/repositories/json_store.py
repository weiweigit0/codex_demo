from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional


class JsonStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def list(self, collection: str) -> List[dict]:
        data = self._read(collection)
        return list(data.values())

    def get(self, collection: str, item_id: str) -> Optional[dict]:
        return self._read(collection).get(item_id)

    def upsert(self, collection: str, item_id: str, value: dict) -> dict:
        with self._lock:
            data = self._read(collection)
            data[item_id] = value
            self._write(collection, data)
        return value

    def delete(self, collection: str, item_id: str) -> bool:
        with self._lock:
            data = self._read(collection)
            existed = item_id in data
            if existed:
                del data[item_id]
                self._write(collection, data)
            return existed

    def append(self, collection: str, value: dict, id_key: str = "id") -> dict:
        item_id = value[id_key]
        return self.upsert(collection, item_id, value)

    def _path(self, collection: str) -> Path:
        return self.root / f"{collection}.json"

    def _read(self, collection: str) -> Dict[str, Any]:
        path = self._path(collection)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _write(self, collection: str, data: Dict[str, Any]):
        path = self._path(collection)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
