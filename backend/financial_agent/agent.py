from __future__ import annotations

import json
from typing import Optional

from backend.company_profile.llm_client import ModelProviderClient


PROMPT_VERSION = "financial_agent_v4"


class FinancialAnalysisAgent:
    """DeepSeek analysis over validated facts and canonical evidence blocks."""

    def __init__(self, llm_client: Optional[ModelProviderClient] = None):
        self.llm_client = llm_client or ModelProviderClient()

    def analyze(self, company: dict, facts: list[dict], blocks: list[dict], period_type: str, periods: list[str]) -> dict:
        if not self.llm_client.available:
            return self._unavailable("未配置 %s 的 API Key。" % self.llm_client.provider.upper())
        allowed_ids = {item["block_id"] for item in blocks}
        observations_payload = self._chat_chinese_json(
            _facts_system(), _facts_prompt(company, facts, blocks), timeout=120,
            ignored_keys={"evidence_block_ids", "category", "trend", "period"},
        )
        if not observations_payload:
            return self._unavailable("财务事实抽取阶段未返回有效 JSON。")
        observations = _validated_items(observations_payload.get("observations"), allowed_ids, "evidence_block_ids")
        risk_facts = _identified_risk_facts(
            _validated_items(observations_payload.get("risk_facts"), allowed_ids, "evidence_block_ids")
        )
        coverage_gaps = []
        covered_periods = {item.get("period") for item in observations if item.get("period")}
        for period in periods:
            if period in covered_periods:
                continue
            period_blocks = [item for item in blocks if item.get("report_period") == period]
            if not period_blocks:
                coverage_gaps.append("%s 未找到可用披露证据块。" % period)
                continue
            period_facts = [item for item in facts if item.get("period") == period]
            focused_payload = self._chat_chinese_json(
                _facts_system(), _facts_prompt(company, period_facts, period_blocks), timeout=90,
                ignored_keys={"evidence_block_ids", "category", "trend", "period"},
            ) or {}
            focused_observations = _validated_items(focused_payload.get("observations"), allowed_ids, "evidence_block_ids")
            focused_observations = [item for item in focused_observations if item.get("period") == period]
            if focused_observations:
                observations.extend(focused_observations[:4])
                covered_periods.add(period)
            else:
                coverage_gaps.append("%s 未能从披露证据中抽取可验证观察。" % period)
        interpretation_payload = self._chat_chinese_json(
            _analysis_system(), _analysis_prompt(company, facts, observations, period_type, periods), timeout=120
        )
        if not interpretation_payload:
            return self._unavailable("财务趋势分析阶段未返回有效 JSON。", observations, risk_facts)
        assessments_payload = self._chat_chinese_json(
            _risk_system(), _risk_prompt(risk_facts, facts), timeout=90,
            ignored_keys={"evidence_fact_ids", "attention_level"},
        ) or {}
        assessments = _risk_assessments(assessments_payload.get("risk_assessments"), risk_facts)
        return {
            "status": "completed",
            "financial_summary": _text(interpretation_payload.get("financial_summary")) or "披露资料不足，无法形成完整财务总结。",
            "trend_analysis": _texts(interpretation_payload.get("trend_analysis")),
            "earnings_quality": _texts(interpretation_payload.get("earnings_quality")),
            "cash_flow_analysis": _texts(interpretation_payload.get("cash_flow_analysis")),
            "balance_sheet_analysis": _texts(interpretation_payload.get("balance_sheet_analysis")),
            "industry_position": _texts(interpretation_payload.get("industry_position")),
            "uncertainties": _texts(interpretation_payload.get("uncertainties")) + coverage_gaps,
            "observations": observations,
            "risk_facts": risk_facts,
            "risk_assessments": assessments,
            "generation_meta": {"agent_version": PROMPT_VERSION, "llm_provider": self.llm_client.provider, "llm_model": self.llm_client.model, "extraction_mode": "financial_two_stage_agent"},
        }

    def _chat_chinese_json(self, system_prompt: str, user_prompt: str, timeout: int, ignored_keys=None) -> Optional[dict]:
        """Retry once when an English filing makes the model answer in English.

        The source material for US filings is usually English, but every free-text
        field is rendered directly in the Chinese product UI. A retry is safer than
        attempting a local machine translation, which could alter financial meaning.
        """
        payload = self.llm_client.chat_json(system_prompt, user_prompt, timeout=timeout)
        if payload and _has_non_chinese_free_text(payload, ignored_keys=ignored_keys):
            payload = self.llm_client.chat_json(
                system_prompt + "\n这是面向中国用户的产品。上一版存在英文自由文本；请重新输出。除 JSON 枚举值、股票代码和专有名词原文外，所有面向用户的文本字段必须使用简体中文。",
                user_prompt,
                timeout=timeout,
            )
        return payload

    def _unavailable(self, reason: str, observations=None, risk_facts=None) -> dict:
        return {"status": "unavailable", "financial_summary": "财报分析 Agent 暂不可用：%s" % reason, "trend_analysis": [], "earnings_quality": [], "cash_flow_analysis": [], "balance_sheet_analysis": [], "industry_position": [], "uncertainties": [reason], "observations": observations or [], "risk_facts": risk_facts or [], "risk_assessments": [], "generation_meta": {"agent_version": PROMPT_VERSION, "llm_provider": self.llm_client.provider, "llm_model": self.llm_client.model, "extraction_mode": "agent_unavailable"}}


def _facts_system() -> str:
    return "你是严谨的财报事实抽取 Agent。只能依据输入的已验证财务事实和披露证据块输出 JSON。不得编造数值、原因或行业信息。每条 observation/risk_fact 必须引用真实 evidence_block_ids。若任务选择多个报告期，必须尽量让 observation 覆盖每个报告期；某期无足够文本证据时，必须在 coverage_gaps 中明确说明，不能用其他期间替代。所有面向用户的自由文本字段必须使用简体中文；英文原始披露只能作为理解依据，不得直接以英文句子输出。JSON 枚举值、股票代码和必要的公司/产品专有名词可保留原文。"


def _facts_prompt(company, facts, blocks) -> str:
    schema = {"observations": [{"category": "revenue_driver|profitability|cash_flow|balance_sheet|business_change", "claim": "", "period": "", "evidence_block_ids": [""]}], "risk_facts": [{"risk_category": "", "risk_name": "", "description": "", "trend": "improved|deteriorated|stable|unknown", "mitigation_disclosed": [], "evidence_block_ids": [""]}], "coverage_gaps": [{"period": "", "reason": ""}]}
    compact_blocks = [{"block_id": item["block_id"], "report_period": item.get("report_period"), "page": item.get("page_number"), "section": item.get("section_title"), "text": item.get("text", "")[:1200]} for item in blocks[:60]]
    return "公司：%s（%s）\n已验证财务事实：%s\n披露证据块：%s\n输出 Schema：%s" % (company.get("name"), company.get("ticker"), json.dumps(facts, ensure_ascii=False), json.dumps(compact_blocks, ensure_ascii=False), json.dumps(schema, ensure_ascii=False))


def _analysis_system() -> str:
    return "你是财报趋势分析 Agent。只能依据输入的财务事实与已抽取 observations 输出 JSON。区分事实与解释；无法确认时写入 uncertainties；禁止投资建议。所有 financial_summary、trend_analysis、earnings_quality、cash_flow_analysis、balance_sheet_analysis、industry_position、uncertainties 的文本必须使用简体中文。英文财报仅供理解，不能直接输出英文句子；专有名词可在中文句子中保留原文。"


def _analysis_prompt(company, facts, observations, period_type, periods) -> str:
    schema = {"financial_summary": "", "trend_analysis": [], "earnings_quality": [], "cash_flow_analysis": [], "balance_sheet_analysis": [], "industry_position": [], "uncertainties": []}
    return "公司：%s\n期间类型：%s；选择期间：%s\n财务事实：%s\n披露观察：%s\n输出 Schema：%s" % (company.get("name"), period_type, periods, json.dumps(facts, ensure_ascii=False), json.dumps(observations, ensure_ascii=False), json.dumps(schema, ensure_ascii=False))


def _risk_system() -> str:
    return "你是财报风险等级评估 Agent。只能基于输入风险事实和已验证数值判断关注等级，不能新增风险事实或投资建议。输出 JSON。所有风险类别、评估理由、正负面信号和不确定性说明必须使用简体中文；attention_level 等 JSON 枚举值除外。"


def _risk_prompt(risk_facts, facts) -> str:
    schema = {"risk_assessments": [{"risk_category": "", "attention_level": "high|medium|low|unknown", "assessment_reason": "", "positive_signals": [], "negative_signals": [], "uncertainties": [], "evidence_fact_ids": []}]}
    return "风险事实：%s\n已验证数值：%s\n输出 Schema：%s" % (json.dumps(risk_facts, ensure_ascii=False), json.dumps(facts, ensure_ascii=False), json.dumps(schema, ensure_ascii=False))


def _validated_items(items, allowed_ids, ref_key):
    result = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        refs = [value for value in item.get(ref_key, []) if value in allowed_ids]
        if not refs:
            continue
        if _has_non_chinese_free_text(item, ignored_keys={ref_key, "category", "trend", "period"}):
            continue
        result.append({**item, ref_key: refs})
    return result[:20]


def _risk_assessments(items, risk_facts):
    valid_ids = {item["fact_id"] for item in risk_facts if item.get("fact_id")}
    result = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        refs = [ref for ref in item.get("evidence_fact_ids", []) if ref in valid_ids]
        if not refs:
            continue
        if _has_non_chinese_free_text(item, ignored_keys={"evidence_fact_ids", "attention_level"}):
            continue
        level = item.get("attention_level") if item.get("attention_level") in {"high", "medium", "low", "unknown"} else "unknown"
        result.append({**item, "attention_level": level, "evidence_fact_ids": refs})
    return result[:12]


def _identified_risk_facts(items):
    """Give stage-one facts stable ids that the assessment stage must cite."""
    return [{**item, "fact_id": "risk_fact_%d" % index} for index, item in enumerate(items)]


def _text(value):
    text = str(value).strip() if isinstance(value, str) else ""
    return text if not _is_non_chinese_free_text(text) else ""


def _texts(value):
    return [_text(item) for item in value or [] if _text(item)][:12]


def _has_non_chinese_free_text(value, ignored_keys=None) -> bool:
    """Detect Latin-only prose while ignoring machine-readable schema values."""
    ignored_keys = ignored_keys or set()
    if isinstance(value, dict):
        return any(
            key not in ignored_keys and _has_non_chinese_free_text(item, ignored_keys)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_has_non_chinese_free_text(item, ignored_keys) for item in value)
    return isinstance(value, str) and _is_non_chinese_free_text(value)


def _is_non_chinese_free_text(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    has_han = any("\u4e00" <= char <= "\u9fff" for char in text)
    has_latin = any(("a" <= char.lower() <= "z") for char in text)
    return has_latin and not has_han
