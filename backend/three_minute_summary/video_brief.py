from __future__ import annotations

import hashlib
import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from backend.media_production.security import env_multiline, sign_payload


VIDEO_BRIEF_VERSION = "video_brief_v1"


def export_video_brief(script: dict, requester: dict) -> dict:
    private_key = env_multiline("VIDEO_BRIEF_PRIVATE_KEY")
    subject_salt = os.getenv("VIDEO_BRIEF_SUBJECT_SALT", "").strip()
    if not private_key or not subject_salt:
        raise RuntimeError("未配置 VideoBrief 签名密钥；请配置 VIDEO_BRIEF_PRIVATE_KEY 和 VIDEO_BRIEF_SUBJECT_SALT。")
    segments = []
    for index, item in enumerate(script.get("segments", []), start=1):
        refs = [str(ref) for ref in item.get("evidence_refs", []) if str(ref)]
        metrics = [str(value).strip() for value in item.get("on_screen_metrics", []) if str(value).strip()]
        segments.append({
            "segment_id": "seg_%02d" % index,
            "title": str(item.get("title") or "本期解读").strip(),
            "target_duration_seconds": max(8, min(60, int(item.get("duration_seconds", 20)))),
            "narration": str(item.get("narration") or "").strip(),
            "visual_direction": str(item.get("visual_direction") or "数据卡片与趋势图").strip(),
            # The current script has verified display labels but no typed numeric
            # cards. Keep values empty rather than having a media service infer them.
            "display_facts": [{"fact_id": "script_metric_%02d_%02d" % (index, metric_index), "label": metric, "display_value": None, "period_label": script.get("period"), "evidence_refs": refs} for metric_index, metric in enumerate(metrics, start=1)],
            "evidence_refs": refs,
        })
    if len(segments) < 4:
        raise ValueError("当前脚本缺少足够可引用分镜，无法导出视频生产包。")
    now = datetime.now(timezone.utc)
    requester_reference = hashlib.sha256((subject_salt + ":" + str(requester["id"])).encode("utf-8")).hexdigest()
    payload = {
        "schema_version": VIDEO_BRIEF_VERSION,
        "brief_id": "brief_%s" % uuid.uuid4().hex[:16],
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=30)).isoformat(),
        "nonce": secrets.token_urlsafe(24),
        "requester_reference": requester_reference,
        "source": {
            "summary_id": script["summary_id"], "script_id": script["script_id"],
            "script_version": script.get("generation_meta", {}).get("agent_version", "three_minute_video"),
            "company_display_name": script.get("company", {}).get("name", "公司"),
            "period_display_name": script.get("period", "报告期"),
        },
        "segments": segments,
        "content_rules": {"language": "zh-CN", "no_new_facts": True, "no_investment_advice": True},
        "key_id": os.getenv("VIDEO_BRIEF_KEY_ID", "financial-mining-video-v1"),
    }
    payload["content_hash"] = hashlib.sha256(_canonical(payload)).hexdigest()
    payload["signature"] = sign_payload(payload, private_key)
    return payload


def _canonical(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
