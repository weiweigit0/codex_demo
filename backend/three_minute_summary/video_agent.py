from __future__ import annotations

import json
import re
from typing import Optional

from backend.company_profile.llm_client import ModelProviderClient


VIDEO_PROMPT_VERSION = "three_minute_video_v3"


class VideoScriptAgent:
    def __init__(self, llm_client: Optional[ModelProviderClient] = None):
        self.llm_client = llm_client or ModelProviderClient()

    def generate(self, summary: dict) -> dict:
        if not self.llm_client.available:
            return {"status": "unavailable", "segments": [], "reason": "未配置模型 API Key。"}
        payload = self.llm_client.chat_json(_system(), _prompt(summary), timeout=120) or {}
        known = _evidence_ids(summary)
        segments = []
        for item in payload.get("segments", []):
            if not isinstance(item, dict):
                continue
            refs = [ref for ref in item.get("evidence_refs", []) if ref in known]
            narration = _safe_narration(str(item.get("narration", "")).strip())
            if not refs or not narration:
                continue
            duration = max(12, min(42, int(item.get("duration_seconds", 20))))
            segments.append({"segment_no": len(segments) + 1, "duration_seconds": duration, "title": str(item.get("title", "本期解读")).strip(), "narration": narration, "visual_direction": str(item.get("visual_direction", "数据卡片与趋势图")).strip(), "on_screen_metrics": [str(value).strip() for value in item.get("on_screen_metrics", []) if str(value).strip()][:3], "evidence_refs": refs})
        if len(segments) < 4:
            return {"status": "unavailable", "segments": [], "reason": "脚本缺少足够的可引用分镜。"}
        return {"status": "completed", "segments": segments[:8], "generation_meta": {"agent_version": VIDEO_PROMPT_VERSION, "llm_provider": self.llm_client.provider, "llm_model": self.llm_client.model}}


def _system():
    return "你是财经短视频编导。只能把输入总结中已确认的事实改写成通俗中文口播与可实现分镜，不得新增数字、预测或投资建议。不得断言某项变化不会影响、一定会改善或必然导致某结果；原文未说明时应使用‘需要继续观察’。每段必须引用真实 evidence_refs。画面建议只能使用数据卡片、趋势图、时间线、公司业务示意或风险提示卡。输出 JSON。"


def _prompt(summary):
    schema = {"segments": [{"title": "", "duration_seconds": 20, "narration": "", "visual_direction": "", "on_screen_metrics": [], "evidence_refs": [""]}]}
    safe = {key: summary.get(key) for key in ("company", "period", "total_score", "one_line_summary", "three_minute_summary", "score_cards", "key_points", "risks", "watch_items", "uncertainties")}
    return "总结资料：%s\n请输出 6 至 8 段、总计约 180 秒的分镜。输出 Schema：%s" % (json.dumps(safe, ensure_ascii=False), json.dumps(schema, ensure_ascii=False))


def _evidence_ids(summary):
    result = set()
    for group in (summary.get("score_cards", []), summary.get("key_points", []), summary.get("risks", [])):
        for item in group:
            result.update(item.get("evidence_block_ids", []))
    return result


def _safe_narration(text: str) -> str:
    """Downgrade deterministic claims that lack a dedicated evidence field."""
    replacements = {
        "不影响主营业务": "对主营业务的具体影响仍需继续观察",
        "不影响公司经营": "对公司经营的具体影响仍需继续观察",
        "一定会": "可能会",
        "必然会": "可能会",
        "必然导致": "可能带来",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return re.sub(r"\s+", " ", text).strip()
