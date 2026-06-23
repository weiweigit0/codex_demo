from __future__ import annotations

import json
import re
from typing import Optional

from backend.company_profile.llm_client import ModelProviderClient


SUMMARY_PROMPT_VERSION = "three_minute_summary_v3"


class ThreeMinuteSummaryAgent:
    def __init__(self, llm_client: Optional[ModelProviderClient] = None):
        self.llm_client = llm_client or ModelProviderClient()

    def generate(self, context: dict) -> dict:
        if not self.llm_client.available:
            return _unavailable("未配置 %s 的 API Key。" % self.llm_client.provider.upper(), self.llm_client)
        payload = self.llm_client.chat_json(_summary_system(), _summary_prompt(context), timeout=150)
        if not payload:
            return _unavailable("模型未返回有效 JSON。", self.llm_client)
        allowed = {item.get("block_id") for item in context["filing_evidence_blocks"] if item.get("block_id")}
        score_cards = _score_cards(payload.get("score_cards"), allowed)
        if len(score_cards) < 4:
            return _unavailable("评分结果缺少足够的可引用证据。", self.llm_client)
        total_score = min(100, sum(item["score"] for item in score_cards))
        return {
            "status": "completed", "total_score": total_score,
            "score_cards": score_cards,
            "one_line_summary": _safe_text(payload.get("one_line_summary")),
            "three_minute_summary": _safe_text(payload.get("three_minute_summary")),
            "key_points": _items(payload.get("key_points"), allowed),
            "risks": _items(payload.get("risks"), allowed),
            "watch_items": _strings(payload.get("watch_items")),
            "uncertainties": _strings(payload.get("uncertainties")),
            "generation_meta": {"agent_version": SUMMARY_PROMPT_VERSION, "llm_provider": self.llm_client.provider, "llm_model": self.llm_client.model},
        }

    def answer(self, summary: dict, question: str, blocks: list[dict]) -> dict:
        if not self.llm_client.available:
            return {"answer": "模型服务暂不可用，暂时无法生成追问回答。", "citations": [], "status": "unavailable"}
        allowed = {item.get("block_id") for item in blocks if item.get("block_id")}
        payload = self.llm_client.chat_json(_qa_system(), _qa_prompt(summary, question, blocks), timeout=90) or {}
        citations = [item for item in payload.get("citations", []) if item in allowed][:5]
        answer = _text(payload.get("answer"))
        if not answer or not citations:
            return {"answer": "当前证据不足以可靠回答这个问题。", "citations": citations, "status": "insufficient_evidence"}
        return {"answer": answer, "citations": citations, "status": "completed"}


def _summary_system() -> str:
    return "你是面向普通人的财报解读 Agent。只依据输入的已验证财务事实、公司事实和披露证据块输出 JSON。评分是经营理解分，不是投资评级；不得给出买卖建议、价格预测或编造信息。严禁使用行业常识、常见风险、外部记忆或未披露的现金、分部、增长、偿债等信息补全结论；证据不足时必须写‘当前证据不足以确认’，并降低置信度。每个评分卡、重点和风险必须引用真实 evidence_block_ids。"


def _summary_prompt(context: dict) -> str:
    schema = {
        "one_line_summary": "", "three_minute_summary": "500至700字的通俗中文总结",
        "score_cards": [{"dimension": "业务清晰度与竞争位置|增长与盈利趋势|现金流与利润质量|资产负债与经营韧性|风险与不确定性|信息披露完整度", "max_score": 20, "score": 0, "reason": "", "confidence": "high|medium|low", "evidence_block_ids": [""]}],
        "key_points": [{"title": "", "text": "", "evidence_block_ids": [""]}],
        "risks": [{"title": "", "text": "", "evidence_block_ids": [""]}],
        "watch_items": ["需继续关注的事项"], "uncertainties": ["无法确认的信息"],
    }
    blocks = [{"block_id": item.get("block_id"), "page": item.get("page_number"), "section": item.get("section_title"), "text": item.get("text", "")[:1200]} for item in context["filing_evidence_blocks"][:48]]
    profile = [{"category": item.get("category"), "claim": item.get("claim"), "source_block_ids": item.get("source_block_ids", [])} for item in context["company_profile_facts"][:12]]
    financial = [{"type": item.get("artifact_type"), "payload": item.get("payload"), "evidence_ids": item.get("evidence_ids", [])} for item in context["financial_agent_artifacts"][:16]]
    return "公司：%s（%s）\n报告期：%s\n已验证财务事实：%s\n公司画像事实：%s\n财报 Agent 产物：%s\n外部补充来源（仅作背景，必须以其证据块引用）：%s\n披露证据：%s\n输出 Schema：%s" % (
        context["company"].get("name"), context["company"].get("ticker"), context["period"],
        json.dumps(context["validated_financial_facts"], ensure_ascii=False), json.dumps(profile, ensure_ascii=False),
        json.dumps(financial, ensure_ascii=False), json.dumps(context.get("external_sources", []), ensure_ascii=False), json.dumps(blocks, ensure_ascii=False), json.dumps(schema, ensure_ascii=False),
    )


def _qa_system() -> str:
    return "你是财报问答 Agent。只能依据输入总结和披露证据回答，语言通俗、禁止投资建议。answer 必须简短直接，citations 必须是实际 block_id；无法确认时明确说明证据不足。输出 JSON。"


def _qa_prompt(summary: dict, question: str, blocks: list[dict]) -> str:
    evidence = [{"block_id": item.get("block_id"), "page": item.get("page_number"), "text": item.get("text", "")[:1200]} for item in blocks[:18]]
    return "问题：%s\n已生成总结：%s\n披露证据：%s\n输出：{\"answer\":\"\",\"citations\":[\"block_id\"]}" % (question, json.dumps(summary, ensure_ascii=False), json.dumps(evidence, ensure_ascii=False))


def _score_cards(items, allowed):
    dimensions = {"业务清晰度与竞争位置": 20, "增长与盈利趋势": 20, "现金流与利润质量": 20, "资产负债与经营韧性": 15, "风险与不确定性": 15, "信息披露完整度": 10}
    result = []
    seen = set()
    for item in items or []:
        if not isinstance(item, dict) or item.get("dimension") not in dimensions or item["dimension"] in seen:
            continue
        refs = [ref for ref in item.get("evidence_block_ids", []) if ref in allowed]
        if not refs:
            continue
        maximum = dimensions[item["dimension"]]
        try:
            score = max(0, min(maximum, int(round(float(item.get("score", 0))))))
        except (TypeError, ValueError):
            continue
        seen.add(item["dimension"])
        result.append({"dimension": item["dimension"], "max_score": maximum, "score": score, "reason": _safe_text(item.get("reason")), "confidence": item.get("confidence") if item.get("confidence") in {"high", "medium", "low"} else "low", "evidence_block_ids": refs})
    return result


def _items(items, allowed):
    result = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        refs = [ref for ref in item.get("evidence_block_ids", []) if ref in allowed]
        if refs and _text(item.get("text")):
            result.append({"title": _safe_text(item.get("title")) or "重点", "text": _safe_text(item.get("text")), "evidence_block_ids": refs})
    return result[:6]


def _strings(value):
    result = []
    for item in value or []:
        text = item.get("text") if isinstance(item, dict) else str(item)
        if text and str(text).strip():
            result.append(str(text).strip())
    return result[:8]


def _text(value):
    return str(value).strip() if isinstance(value, str) else ""


def _safe_text(value):
    """Downgrade common model overclaims when the evidence packet lacks the fact."""
    text = _text(value)
    replacements = {
        "根据行业常识判断大概率增长": "当前证据不足以判断同比增长趋势",
        "根据行业常识": "当前证据不足以确认",
        "实际风险较低": "实际风险仍需结合完整披露进一步确认",
        "风险可控": "风险程度仍需结合完整披露进一步确认",
        "典型的优质蓝筹股": "经营表现需结合后续报告持续观察",
        "自由现金流强劲": "经营现金流表现需结合资本开支进一步确认",
        "现金充裕": "现金状况需结合现金及有价证券披露进一步确认",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return re.sub(r"\s+", " ", text).strip()


def _unavailable(reason, client):
    return {"status": "unavailable", "total_score": None, "score_cards": [], "one_line_summary": "暂无法生成三分钟总结。", "three_minute_summary": reason, "key_points": [], "risks": [], "watch_items": [], "uncertainties": [reason], "generation_meta": {"agent_version": SUMMARY_PROMPT_VERSION, "llm_provider": client.provider, "llm_model": client.model}}
