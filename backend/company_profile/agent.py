from __future__ import annotations

import json
import re
from typing import List, Optional

from backend.company_profile.document_segmenter import DocumentSegmenter
from backend.company_profile.evidence_service import EvidenceService
from backend.company_profile.hallucination_guard import HallucinationGuard
from backend.company_profile.llm_client import ModelProviderClient
from backend.company_profile.profile_schema import (
    AgentProfile,
    AgentResult,
    BusinessModelBlock,
    BusinessSegment,
    CapitalActionsBlock,
    CompanyProfileBlock,
    IndustryChainBlock,
    KeyPerson,
    MissingInformation,
    NonFinancialRisk,
    OwnershipBlock,
)


class CompanyProfileAgent:
    def __init__(self, llm_client: Optional[ModelProviderClient] = None, segmenter: Optional[DocumentSegmenter] = None, guard: Optional[HallucinationGuard] = None):
        self.llm_client = llm_client or ModelProviderClient()
        self.segmenter = segmenter or DocumentSegmenter()
        self.guard = guard or HallucinationGuard()

    def generate(self, company: dict, document: dict, parsed: dict, evidence: EvidenceService, wikipedia_context: Optional[dict] = None) -> AgentResult:
        context_pack = self.segmenter.context_pack(parsed)
        if not self.llm_client.available:
            return self._missing_result(company, document, evidence, reason="未配置 %s 的 API Key，无法启用公司画像 Agent 的大模型抽取。" % self.llm_client.provider.upper())

        payload = self.llm_client.chat_json(
            system_prompt=_system_prompt(),
            user_prompt=_user_prompt(company, document, context_pack, wikipedia_context=wikipedia_context),
            timeout=80,
        )
        if not payload:
            return self._missing_result(company, document, evidence, reason="大模型未返回可解析的结构化 JSON。")

        try:
            profile = self._profile_from_payload(company, payload, evidence)
        except Exception:
            retry_payload = self.llm_client.chat_json(
                system_prompt=_system_prompt(),
                user_prompt=_user_prompt(company, document, context_pack, wikipedia_context=wikipedia_context, retry=True),
                timeout=80,
            )
            if not retry_payload:
                return self._missing_result(company, document, evidence, reason="大模型输出未通过结构化校验，重试后仍失败。")
            profile = self._profile_from_payload(company, retry_payload, evidence)
        generation_meta = {
            "agent_version": "company_profile_agent_v1",
            "extraction_mode": "agent_llm",
            "llm_model": self.llm_client.model,
            "llm_provider": self.llm_client.provider,
            "used_wikipedia": bool(wikipedia_context),
            "missing_information_count": len(profile.missing_information),
            "confidence": _overall_confidence(profile),
        }
        profile, generation_meta = self.guard.review(profile, generation_meta)
        return AgentResult(
            profile=profile,
            generation_meta=generation_meta,
        )

    def generate_two_stage(self, company: dict, document: dict, parsed: dict, evidence: EvidenceService) -> AgentResult:
        if not self.llm_client.available:
            return self._missing_result(company, document, evidence, reason="未配置大模型 API Key。")
        document_facts = []
        for batch in _document_batches(parsed.get("blocks", [])):
            payload = self.llm_client.chat_json(
                _stage_one_system_prompt(),
                _stage_one_prompt(company, batch),
                timeout=120,
            )
            if not payload:
                return self._missing_result(company, document, evidence, reason="完整资料阅读阶段未返回结构化事实。")
            document_facts.append(payload)
        risk_facts = _risk_facts(document_facts, evidence)
        payload = self.llm_client.chat_json(
            _system_prompt(),
            _stage_two_prompt(company, document, document_facts),
            timeout=120,
        )
        if not payload:
            return self._missing_result(company, document, evidence, reason="综合画像阶段未返回结构化 JSON。")
        try:
            profile = self._profile_from_payload(company, payload, evidence)
        except Exception:
            return self._missing_result(company, document, evidence, reason="综合画像未通过结构化校验。")
        meta = {
            "agent_version": "company_profile_agent_v2",
            "extraction_mode": "two_stage_agent",
            "llm_model": self.llm_client.model,
            "llm_provider": self.llm_client.provider,
            "document_fact_batches": len(document_facts),
            "confidence": _overall_confidence(profile),
        }
        profile, meta = self.guard.review(profile, meta)
        risk_assessments = self.llm_client.chat_json(
            _risk_assessment_system_prompt(), _risk_assessment_prompt(risk_facts), timeout=90
        ) or {}
        assessments = _risk_assessments(risk_assessments.get("risk_assessments"), risk_facts)
        meta["risk_assessment_version"] = "v1"
        meta["has_industry_benchmark"] = False
        return AgentResult(profile=profile, generation_meta=meta, risk_facts=risk_facts, risk_assessments=assessments)

    def _profile_from_payload(self, company: dict, payload: dict, evidence: EvidenceService) -> AgentProfile:
        cp_payload = _dict(payload.get("company_profile"))
        bm_payload = _dict(payload.get("business_model"))
        own_payload = _dict(payload.get("ownership"))
        chain_payload = _dict(payload.get("industry_chain"))
        capital_payload = _dict(payload.get("capital_actions"))

        business_ev = _evidence_from_payload(evidence, "business_model", cp_payload.get("main_business") or bm_payload.get("business_summary"), payload, "business_model")
        ownership_ev = _evidence_from_payload(evidence, "ownership", own_payload.get("actual_controller") or own_payload.get("controlling_shareholder"), payload, "ownership")
        people_ev = _evidence_from_payload(evidence, "key_people", "关键人物", payload, "key_people")
        chain_ev = _evidence_from_payload(evidence, "industry_chain", "产业链", payload, "industry_chain")
        capital_ev = _evidence_from_payload(evidence, "capital_actions", capital_payload.get("summary"), payload, "capital_actions")
        risk_ev = _evidence_from_payload(evidence, "non_financial_risk", "非财务风险", payload, "non_financial_risks")

        main_business = _clean_text(cp_payload.get("main_business") or bm_payload.get("business_summary")) or "未披露"
        industry = _clean_text(cp_payload.get("industry")) or "未披露"
        shareholder = _clean_text(own_payload.get("controlling_shareholder")) or "未披露"
        controller = _clean_text(own_payload.get("actual_controller")) or "未披露"
        business_segments = _business_segments(bm_payload, main_business, business_ev, company.get("name") or "")
        people = _people(payload.get("key_people"), people_ev)
        risks = _risks(payload.get("non_financial_risks"), risk_ev)
        missing = _missing(payload.get("missing_information"))

        evidence_refs = [ref for ref in [business_ev, ownership_ev, people_ev, chain_ev, capital_ev, risk_ev] if ref]
        return AgentProfile(
            company_profile=CompanyProfileBlock(
                full_name=company["name"],
                short_name=company.get("short_name") or company["name"],
                stock_code=company["ticker"],
                market=_profile_market(company),
                exchange=company.get("exchange"),
                industry=industry,
                main_business=main_business,
                controlling_shareholder=shareholder,
                actual_controller=controller,
                headquarters=_clean_text(cp_payload.get("headquarters")),
                evidence_refs=[ref for ref in [business_ev, ownership_ev] if ref],
            ),
            business_model=BusinessModelBlock(
                business_summary=main_business,
                business_segments=business_segments,
                evidence_refs=[business_ev] if business_ev else [],
            ),
            ownership=OwnershipBlock(
                controlling_shareholder=shareholder,
                actual_controller=controller,
                control_type=_clean_text(own_payload.get("control_type")) or _control_type(controller, shareholder),
                shareholders=_list_of_dicts(own_payload.get("shareholders")),
                ownership_tags=_list_of_text(own_payload.get("ownership_tags")) or _ownership_tags(controller, shareholder),
                plain_explanation=_clean_text(own_payload.get("plain_explanation")) or _plain_ownership(controller, shareholder),
                evidence_refs=[ownership_ev] if ownership_ev else [],
            ),
            key_people=people,
            industry_chain=IndustryChainBlock(
                upstream=_list_of_text(chain_payload.get("upstream")),
                company_position=_clean_text(chain_payload.get("company_position")) or main_business,
                downstream=_list_of_text(chain_payload.get("downstream")),
                end_users=_list_of_text(chain_payload.get("end_users")),
                major_customers=_list_of_text(chain_payload.get("major_customers")),
                major_suppliers=_list_of_text(chain_payload.get("major_suppliers")),
                bargaining_power_note=_clean_text(chain_payload.get("bargaining_power_note")) or "不进行竞争力或议价能力评级。",
                risk_note=_clean_text(chain_payload.get("risk_note")) or "如披露客户或供应商集中，建议查看风险章节。",
                evidence_refs=[chain_ev] if chain_ev else [],
            ),
            capital_actions=CapitalActionsBlock(
                dividends=_list_of_dicts(capital_payload.get("dividends")),
                buybacks=_list_of_dicts(capital_payload.get("buybacks")),
                equity_incentives=_list_of_dicts(capital_payload.get("equity_incentives")),
                financing_actions=_list_of_dicts(capital_payload.get("financing_actions")),
                summary=_clean_text(capital_payload.get("summary")) or "未披露或无法确认。",
                evidence_refs=[capital_ev] if capital_ev else [],
            ),
            non_financial_risks=risks,
            missing_information=missing,
            evidence_refs=evidence_refs,
        )

    def _missing_result(self, company: dict, document: dict, evidence: EvidenceService, reason: str) -> AgentResult:
        missing_ev = evidence.create("agent_missing", reason, "公司画像 Agent", ["主营业务", "公司简介", "风险"], confidence="MISSING")
        profile = AgentProfile(
            company_profile=CompanyProfileBlock(
                full_name=company["name"],
                short_name=company.get("short_name") or company["name"],
                stock_code=company["ticker"],
                market=_profile_market(company),
                exchange=company.get("exchange"),
                evidence_refs=[missing_ev],
            ),
            business_model=BusinessModelBlock(
                business_summary="公司画像 Agent 未完成结构化抽取。",
                business_segments=[
                    BusinessSegment(
                        name="待抽取",
                        core_products_or_services=[],
                        revenue_source_description="未启用大模型时不再使用规则猜测业务内容。",
                        plain_explanation="请配置大模型 API Key 后重新生成，以获得基于披露文件的公司画像。",
                        evidence_refs=[missing_ev],
                    )
                ],
                evidence_refs=[missing_ev],
            ),
            ownership=OwnershipBlock(evidence_refs=[missing_ev]),
            key_people=[],
            industry_chain=IndustryChainBlock(evidence_refs=[missing_ev]),
            capital_actions=CapitalActionsBlock(evidence_refs=[missing_ev]),
            non_financial_risks=[],
            missing_information=[
                MissingInformation(field="company_profile", reason=reason, suggested_source="配置大模型 API Key 后重新生成"),
                MissingInformation(field="business_model", reason="未使用规则兜底，避免错误抽取。", suggested_source="年报或招股说明书"),
            ],
            evidence_refs=[missing_ev],
        )
        generation_meta = {
            "agent_version": "company_profile_agent_v1",
            "extraction_mode": "agent_missing",
            "llm_model": self.llm_client.model,
            "llm_provider": self.llm_client.provider,
            "used_wikipedia": False,
            "missing_information_count": len(profile.missing_information),
            "confidence": "low",
        }
        profile, generation_meta = self.guard.review(profile, generation_meta)
        return AgentResult(
            profile=profile,
            generation_meta=generation_meta,
        )


def _system_prompt() -> str:
    return (
        "你是严谨的上市公司公司画像生成 Agent。你只能基于用户提供的公开披露文件片段输出事实。"
        "禁止编造，禁止估值判断，禁止买卖建议，禁止推断未给出的财务结论。披露文件可能为英文，"
        "请用中文解释已确认事实，但公司、人名、产品名等专有名词可保留原文。"
        "如果信息不足，必须写入 missing_information。输出必须是 JSON。"
    )


def _stage_one_system_prompt() -> str:
    return (
        "你是上市公司披露文件事实抽取 Agent。完整阅读输入的所有文本块，只提取原文明确支持的事实。"
        "每条事实必须返回原始 block_id；不得推断、不得使用常识补全。输出 JSON。"
    )


def _stage_one_prompt(company: dict, blocks: List[dict]) -> str:
    schema = {
        "document_facts": [
            {"category": "business_model|ownership|key_people|industry_chain|capital_actions|non_financial_risks|basic_info",
             "claim": "", "block_ids": ["doc1_txt_001"], "source_type": "filing|wikipedia|baidu_baike",
             "risk_category": "", "risk_name": "", "trend": "improved|deteriorated|stable|unknown", "mitigation_disclosed": []}
        ],
        "missing_information": []
    }
    return "公司：%s（%s）\n只返回 JSON。Schema：%s\n完整文本块：%s" % (
        company.get("name"), company.get("ticker"), json.dumps(schema, ensure_ascii=False), json.dumps(blocks, ensure_ascii=False)
    )


def _stage_two_prompt(company: dict, document: dict, document_facts: List[dict]) -> str:
    schema_prompt = _user_prompt(company, document, {"document_facts": document_facts}, wikipedia_context=None)
    return (
        schema_prompt.replace("披露文件片段：", "阶段一事实清单：")
        + "\n综合规则：披露文件优先；百科仅可补充基础背景；每个 evidence 值必须引用阶段一事实中的真实 block_id。"
    )


def _risk_assessment_system_prompt() -> str:
    return "你是风险强度评估 Agent。只能依据输入风险事实评级，不得生成新事实或投资建议。输出 JSON。"


def _risk_assessment_prompt(risk_facts: List[dict]) -> str:
    schema = {"risk_assessments": [{"risk_category": "", "attention_level": "high|medium|low|unknown", "assessment_reason": "", "positive_signals": [], "negative_signals": [], "uncertainties": [], "evidence_fact_ids": []}]}
    rubric = "high=重大事件/处罚/持续恶化且无缓释；medium=存在不利暴露；low=常规提示且有改善证据；unknown=证据或行业基准不足。"
    return "评级规则：%s\n风险事实：%s\nSchema：%s" % (rubric, json.dumps(risk_facts, ensure_ascii=False), json.dumps(schema, ensure_ascii=False))


def _risk_facts(document_facts: List[dict], evidence: EvidenceService) -> List[dict]:
    facts = []
    for batch in document_facts:
        for item in _list_of_dicts(batch.get("document_facts")):
            if item.get("category") != "non_financial_risks":
                continue
            block_ids = _list_of_text(item.get("block_ids"))
            block_id = next((value for value in block_ids if evidence.block_by_id(value)), "")
            if not block_id:
                continue
            fact_id = "risk_fact_%s" % len(facts)
            ref = evidence.create_from_block_id("risk_fact", _clean_text(item.get("claim")) or "风险事实", block_id)
            facts.append({
                "fact_id": fact_id,
                "risk_category": _clean_text(item.get("risk_category")) or "披露风险",
                "risk_name": _clean_text(item.get("risk_name")) or _clean_text(item.get("claim")) or "风险事实",
                "description": _clean_text(item.get("claim")),
                "trend": _clean_text(item.get("trend")) or "unknown",
                "mitigation_disclosed": _list_of_text(item.get("mitigation_disclosed")),
                "evidence_refs": [ref],
                "evidence_block_ids": [block_id],
            })
    return facts[:20]


def _risk_assessments(value, risk_facts: List[dict]) -> List[dict]:
    fact_ids = {item["fact_id"] for item in risk_facts}
    assessments = []
    for item in _list_of_dicts(value):
        level = _clean_text(item.get("attention_level")).lower() or "unknown"
        if level not in {"high", "medium", "low", "unknown"}:
            level = "unknown"
        ids = [item_id for item_id in _list_of_text(item.get("evidence_fact_ids")) if item_id in fact_ids]
        assessments.append({
            "risk_category": _clean_text(item.get("risk_category")) or "披露风险",
            "attention_level": level,
            "assessment_reason": _clean_text(item.get("assessment_reason")) or "缺少充分评级依据。",
            "positive_signals": _list_of_text(item.get("positive_signals")),
            "negative_signals": _list_of_text(item.get("negative_signals")),
            "uncertainties": _list_of_text(item.get("uncertainties")) or (["未引入行业基准"] if level == "unknown" else []),
            "evidence_fact_ids": ids,
        })
    return assessments


def _document_batches(blocks: List[dict], max_chars: int = 600000) -> List[List[dict]]:
    batches, current, size = [], [], 0
    for block in blocks:
        block_size = len(str(block.get("text", "")))
        if current and size + block_size > max_chars:
            batches.append(current)
            current, size = [], 0
        current.append({key: value for key, value in block.items() if key in {"id", "page", "section_title", "text", "document"}})
        size += block_size
    if current:
        batches.append(current)
    return batches


def _user_prompt(company: dict, document: dict, context_pack: dict, wikipedia_context: Optional[dict] = None, retry: bool = False) -> str:
    schema = {
        "company_profile": {
            "industry": "",
            "main_business": "",
            "headquarters": "",
        },
        "business_model": {
            "business_summary": "",
            "business_segments": [
                {
                    "name": "",
                    "core_products_or_services": [],
                    "revenue_source_description": "",
                    "plain_explanation": "",
                }
            ],
        },
        "ownership": {
            "controlling_shareholder": "",
            "actual_controller": "",
            "control_type": "state_owned_or_state_related|controlled|no_actual_controller|unknown",
            "shareholders": [],
            "ownership_tags": [],
            "plain_explanation": "",
        },
        "key_people": [
            {
                "name": "",
                "role": "",
                "background": "",
                "importance_reason": "",
                "tags": [],
                "source_type": "filing",
            }
        ],
        "industry_chain": {
            "upstream": [],
            "company_position": "",
            "downstream": [],
            "end_users": [],
            "major_customers": [],
            "major_suppliers": [],
            "bargaining_power_note": "",
            "risk_note": "",
        },
        "capital_actions": {
            "dividends": [],
            "buybacks": [],
            "equity_incentives": [],
            "financing_actions": [],
            "summary": "",
        },
        "non_financial_risks": [
            {
                "risk_name": "",
                "risk_type": "",
                "severity": "low|medium|high|unknown",
                "plain_explanation": "",
                "source_type": "filing",
            }
        ],
        "missing_information": [
            {"field": "", "reason": "", "suggested_source": ""}
        ],
        "evidence": {
            "business_model": ["txt_001"],
            "ownership": ["txt_002"],
            "key_people": ["txt_003"],
            "industry_chain": ["txt_004"],
            "capital_actions": ["txt_005"],
            "non_financial_risks": ["txt_006"]
        },
    }
    return (
        "公司：%s（%s）\n"
        "来源文件：%s\n"
        "资料类型：%s\n"
        "要求：只返回 JSON；每个字段只写能从片段中确认的信息；不知道就留空并加入 missing_information。"
        "evidence 中每个键必须填写支撑该部分结论的 block_id；没有明确支持时填空数组，禁止猜测。\n"
        "%s"
        "百科资料仅在披露文件未披露相关基础信息时才可补充，披露文件优先；不得用百科补充股权、实控人、风险和财务结论。"
        "如披露文件和百科都没有明确依据，必须加入 missing_information。\n\n"
        "JSON Schema 示例：\n%s\n\n"
        "维基百科补充：\n%s\n\n"
        "披露文件片段：\n%s"
        % (
            company.get("name"),
            company.get("ticker"),
            document.get("title") or document.get("period"),
            document.get("report_type"),
            "上一次输出未通过校验，请严格按 JSON schema 重试，不要添加解释文字。\n" if retry else "",
            json.dumps(schema, ensure_ascii=False),
            json.dumps(wikipedia_context or {}, ensure_ascii=False),
            json.dumps(context_pack, ensure_ascii=False),
        )
    )


def _evidence_from_payload(evidence: EvidenceService, claim_type: str, claim: Optional[str], payload: dict, evidence_key: str) -> str:
    block_id = _first_block_id(_dict(payload.get("evidence")).get(evidence_key))
    if not block_id or not evidence.block_by_id(block_id):
        return ""
    return evidence.create_from_block_id(claim_type, _clean_text(claim) or claim_type, block_id)


def _first_block_id(refs) -> str:
    if isinstance(refs, list) and refs:
        return str(refs[0])
    return ""


def _business_segments(payload: dict, main_business: str, evidence_ref: str, company_name: str) -> List[BusinessSegment]:
    segments = []
    for item in _list_of_dicts(payload.get("business_segments")):
        segments.append(
            BusinessSegment(
                name=_clean_text(item.get("name")) or "主营业务",
                core_products_or_services=_list_of_text(item.get("core_products_or_services")),
                revenue_source_description=_clean_text(item.get("revenue_source_description")) or "公司通过披露文件所述产品或服务获得收入。",
                plain_explanation=_clean_text(item.get("plain_explanation")) or _plain_business(company_name, main_business),
                evidence_refs=[evidence_ref] if evidence_ref else [],
            )
        )
    if not segments:
        segments.append(
            BusinessSegment(
                name="主营业务",
                core_products_or_services=[],
                revenue_source_description="公司通过披露文件所述产品或服务获得收入。",
                plain_explanation=_plain_business(company_name, main_business),
                evidence_refs=[evidence_ref] if evidence_ref else [],
            )
        )
    return segments[:5]


def _people(value, evidence_ref: str) -> List[KeyPerson]:
    people = []
    for item in _list_of_dicts(value):
        name = _clean_text(item.get("name"))
        if not name:
            continue
        people.append(
            KeyPerson(
                name=name,
                role=_clean_text(item.get("role")) or "关键人物",
                background=_clean_text(item.get("background")),
                importance_reason=_clean_text(item.get("importance_reason")) or "披露文件显示该人物与公司治理、技术或经营管理相关。",
                tags=_list_of_text(item.get("tags")) or ["关键人物"],
                source_type=_clean_text(item.get("source_type")) or "filing",
                evidence_refs=[evidence_ref] if evidence_ref else [],
            )
        )
    return people[:8]


def _risks(value, evidence_ref: str) -> List[NonFinancialRisk]:
    risks = []
    for item in _list_of_dicts(value):
        name = _clean_text(item.get("risk_name"))
        if not name:
            continue
        severity = (_clean_text(item.get("severity")) or "unknown").lower()
        if severity not in {"low", "medium", "high", "unknown"}:
            severity = "unknown"
        risks.append(
            NonFinancialRisk(
                risk_name=name,
                risk_type=_clean_text(item.get("risk_type")) or "非财务风险",
                severity=severity,
                plain_explanation=_clean_text(item.get("plain_explanation")) or "披露文件提示该事项可能影响公司经营。",
                source_type=_clean_text(item.get("source_type")) or "filing",
                evidence_refs=[evidence_ref] if evidence_ref else [],
            )
        )
    return risks[:8]


def _missing(value) -> List[MissingInformation]:
    items = []
    for item in _list_of_dicts(value):
        field = _clean_text(item.get("field"))
        reason = _clean_text(item.get("reason"))
        if field and reason:
            items.append(MissingInformation(field=field, reason=reason, suggested_source=_clean_text(item.get("suggested_source")) or "公司公告或官方披露文件"))
    return items[:12]


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _list_of_dicts(value) -> List[dict]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _list_of_text(value) -> List[str]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        text = _clean_text(item)
        if text and text not in out and text not in {"未知", "未披露", "不详"}:
            out.append(text)
    return out[:10]


def _clean_text(value) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if text in {"未知", "无", "未披露", "不详", "None", "null"}:
        return ""
    return text[:300]


def _plain_business(name: str, business: str) -> str:
    if not business or business == "未披露":
        return "当前资料中未能确认公司的主营业务。"
    return "%s主要围绕“%s”开展业务。" % (name, business[:90])


def _plain_ownership(controller: str, shareholder: str) -> str:
    if controller == "未披露" and shareholder == "未披露":
        return "当前披露文件中未能确认控股股东或实际控制人。"
    return "披露文件显示，%s对公司治理具有重要影响。" % ((shareholder if shareholder != "未披露" else controller)[:80])


def _control_type(controller: str, shareholder: str) -> str:
    text = "%s%s" % (controller, shareholder)
    if "国资" in text or "国有" in text:
        return "state_owned_or_state_related"
    if "无实际控制人" in text:
        return "no_actual_controller"
    if "未披露" in text:
        return "unknown"
    return "controlled"


def _ownership_tags(controller: str, shareholder: str) -> List[str]:
    text = "%s%s" % (controller, shareholder)
    if "国资" in text or "国有" in text:
        return ["国资背景"]
    if "无实际控制人" in text:
        return ["无实际控制人"]
    return ["控制权待进一步核验"] if "未披露" in text else ["存在明确控制关系"]


def _overall_confidence(profile: AgentProfile) -> str:
    if len(profile.missing_information) >= 5:
        return "low"
    if profile.company_profile.evidence_refs and profile.business_model.evidence_refs:
        return "medium"
    return "low"


def _profile_market(company: dict) -> str:
    return "CN_A" if company.get("market") == "CN" else "US"
