from __future__ import annotations

import hashlib
import json
import os
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path

from backend.data_platform.repository import utc_now
from backend.media_production.repository import MediaRepository


TERMINAL = {"REJECTED", "CANCELLED", "DELIVERED", "DEMO_DELIVERED", "FAILED"}


class MediaProductionOrchestrator:
    """Owns media requests without importing finance or summary services."""

    def __init__(self, storage_dir: Path):
        self.repository = MediaRepository(storage_dir)
        self.mode = os.getenv("MEDIA_RENDER_MODE", "disabled").strip().lower()

    def import_brief(self, brief: dict) -> dict:
        item, created = self.repository.import_brief(brief)
        return {"brief_id": item["brief_id"], "created": created, "expires_at": item["expires_at"]}

    def create_request(self, brief_id: str, output_profile: str) -> dict:
        brief = self.repository.get_brief(brief_id)
        if not brief:
            raise KeyError("脚本包不存在")
        if _expired(brief["expires_at"]):
            raise ValueError("脚本包已过期，请返回财报系统重新导出。")
        existing = self.repository.get_request_for_content_hash(brief["content_hash"], brief["requester_reference"])
        if existing:
            return {**self.public_request(existing), "access_token": None, "reused": True}
        token = secrets.token_urlsafe(32)
        total_seconds = sum(item["target_duration_seconds"] for item in brief["segments"])
        estimate = {
            "total_seconds": total_seconds,
            "segment_count": len(brief["segments"]),
            "estimated_clips": sum((item["target_duration_seconds"] + 9) // 10 for item in brief["segments"]),
            "render_mode": self.mode,
            "cost_status": "管理员审批后才会实际消耗模型额度",
        }
        now = utc_now()
        request = {
            "request_id": _id("media_request"), "brief_id": brief_id,
            "requester_reference": brief["requester_reference"],
            "access_token_hash": _digest(token), "output_profile": output_profile,
            "status": "PENDING_REVIEW", "status_note": "已提交，等待管理员审核。",
            "estimate": estimate, "render": {}, "created_at": now, "updated_at": now,
        }
        self.repository.create_request(request)
        self._event(request["request_id"], "requester", "SUBMITTED", "已提交视频生成申请")
        return {**self.public_request(request), "access_token": token, "reused": False}

    def get_request(self, request_id: str, access_token: str = "", admin: bool = False) -> dict:
        request = self.repository.get_request(request_id)
        if not request:
            raise KeyError("视频申请不存在")
        if not admin and not secrets.compare_digest(request["access_token_hash"], _digest(access_token)):
            raise PermissionError("无权查看该视频申请")
        return self.public_request(request, include_events=True, include_assets=True)

    def list_review_queue(self) -> list[dict]:
        return [self.public_request(item, include_brief=True) for item in self.repository.pending_requests()]

    def review(self, request_id: str, action: str, note: str, actor: str) -> dict:
        request = self.repository.get_request(request_id)
        if not request:
            raise KeyError("视频申请不存在")
        if action == "approve":
            if request["status"] not in {"PENDING_REVIEW", "FAILED"}:
                raise ValueError("当前状态不能批准")
            request = self.repository.update_request(request_id, status="QUEUED", status_note="管理员已批准，等待独立媒体 Worker 领取。")
            self._event(request_id, actor, "APPROVED", note or "管理员批准")
        elif action == "retry":
            if request["status"] != "FAILED":
                raise ValueError("只有失败任务可以重试")
            request = self.repository.update_request(request_id, status="QUEUED", status_note="管理员批准重试，等待独立媒体 Worker 领取。")
            self._event(request_id, actor, "RETRY", note or "管理员批准重试")
        elif action == "reject":
            if request["status"] != "PENDING_REVIEW":
                raise ValueError("当前状态不能拒绝")
            request = self.repository.update_request(request_id, status="REJECTED", status_note=note or "管理员未批准本次申请。")
            self._event(request_id, actor, "REJECTED", note or "管理员拒绝")
        else:
            raise ValueError("不支持的审核动作")
        return self.public_request(request, include_events=True)

    def public_request(self, request: dict, include_events: bool = False, include_assets: bool = False, include_brief: bool = False) -> dict:
        result = {key: value for key, value in request.items() if key not in {"access_token_hash", "requester_reference"}}
        if include_events:
            result["events"] = self.repository.events(request["request_id"])
        if include_assets:
            result["assets"] = [{key: value for key, value in asset.items() if key != "relative_path"} for asset in self.repository.assets(request["request_id"])]
        if include_brief:
            result["brief"] = self.repository.get_brief(request["brief_id"])
        return result

    def asset_path(self, request_id: str, asset_id: str, access_token: str = "", admin: bool = False) -> tuple[Path, str]:
        self.get_request(request_id, access_token, admin)
        asset = next((item for item in self.repository.assets(request_id) if item["asset_id"] == asset_id), None)
        if not asset:
            raise KeyError("媒体文件不存在")
        path = self.repository.root / asset["relative_path"]
        if not path.is_file():
            raise KeyError("媒体文件已过期或已删除")
        return path, asset["mime_type"]

    def _event(self, request_id: str, actor: str, action: str, note: str) -> None:
        self.repository.add_event({"event_id": _id("approval"), "request_id": request_id, "actor": actor, "action": action, "note": note, "created_at": utc_now()})


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _id(prefix: str) -> str:
    return "%s_%s" % (prefix, uuid.uuid4().hex[:16])


def _expired(value: str) -> bool:
    return datetime.fromisoformat(value).astimezone(timezone.utc) <= datetime.now(timezone.utc)

