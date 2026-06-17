from __future__ import annotations

import re
import time
import uuid
from typing import Dict, List, Optional

from backend.company_profile.llm_extractor import LLMProfileExtractor
from backend.data_sources.ashare_source import AShareSource


FINANCIAL_TERMS = [
    "现金流",
    "毛利率",
    "净利率",
    "roe",
    "资产负债率",
    "应收账款",
    "存货",
    "盈利能力",
    "偿债",
    "财务健康",
    "收入增长",
    "利润",
]


class CompanyProfileOrchestrator:
    def __init__(self):
        self.ashare_source = AShareSource()
        self.llm_extractor = LLMProfileExtractor()
        self.tasks: Dict[str, dict] = {}
        self.reports: Dict[str, dict] = {}
        self.evidences: Dict[str, dict] = {}

    def create_report(
        self,
        query: str,
        market: str = "auto",
        document_type: str = "auto",
        year: Optional[int] = None,
        report_style: str = "plain",
    ) -> dict:
        task_id = _id("profile_task")
        task = self._task(task_id, query, "RESOLVING_COMPANY", 10, "正在识别公司")
        self.tasks[task_id] = task
        try:
            resolved_document_type = _detect_document_type(query, document_type)
            resolved_year = year or _detect_year(query)
            company_query = _clean_company_query(query)
            normalized_market = _normalize_market(company_query or query, market)
            if normalized_market != "CN":
                raise ValueError("V1 暂只支持 A 股公司画像。")

            company = self.ashare_source.resolve_company(company_query or query)
            task.update(
                {
                    "status": "RETRIEVING_DOCUMENT",
                    "progress": 25,
                    "current_step": _retrieving_step(resolved_document_type),
                    "company": company,
                }
            )
            report_meta = self._select_document(company, document_type=resolved_document_type, year=resolved_year)

            task.update({"status": "PARSING_DOCUMENT", "progress": 55, "current_step": f"正在解析{_document_kind_name(report_meta)} PDF", "document": report_meta})
            text = self.ashare_source.cninfo.extract_pdf_text(report_meta["source_url"])
            parsed = _parse_document_text(text)

            task.update({"status": "EXTRACTING_INFORMATION", "progress": 75, "current_step": "正在抽取公司画像"})
            llm_profile = self.llm_extractor.extract(company, report_meta, parsed)
            report = self._build_report(company, report_meta, parsed, report_style, llm_profile=llm_profile)

            task.update(
                {
                    "status": "COMPLETED",
                    "progress": 100,
                    "current_step": "公司画像已生成",
                    "report_id": report["report_id"],
                    "updated_at": _now(),
                }
            )
            self.reports[report["report_id"]] = report
        except Exception as exc:
            task.update(
                {
                    "status": "FAILED_REPORT_GENERATION",
                    "progress": task.get("progress", 0),
                    "current_step": "公司画像生成失败",
                    "error": {"code": "REPORT_GENERATION_FAILED", "message": str(exc)},
                    "updated_at": _now(),
                }
            )
        return task

    def get_task(self, task_id: str) -> dict:
        if task_id not in self.tasks:
            raise KeyError("任务不存在")
        return self.tasks[task_id]

    def get_report(self, report_id: str) -> dict:
        if report_id not in self.reports:
            raise KeyError("报告不存在")
        return self.reports[report_id]

    def get_evidence(self, evidence_id: str) -> dict:
        if evidence_id not in self.evidences:
            raise KeyError("证据不存在")
        return self.evidences[evidence_id]

    def answer_question(self, report_id: str, question: str) -> dict:
        report = self.get_report(report_id)
        if _is_financial_question(question):
            return {
                "answer_type": "finance_handoff",
                "answer": "这个问题属于财务报表分析范围。当前公司画像主要解释业务、股东、人物、产业链、资本动作和非财务风险，建议进入财报掘金继续分析。",
                "evidence_refs": [],
                "finance_agent_handoff": self._finance_handoff(report, question),
                "suggested_questions": _suggested_questions(),
            }

        lower = question.lower()
        section = _section_for_question(lower, question)
        matched = next((item for item in report["sections"] if item["section_type"] == section), None)
        if not matched:
            matched = next((item for item in report["sections"] if item["section_type"] == "plain_conclusion"), report["sections"][0])
        content = _section_text(matched)
        return {
            "answer_type": "direct_answer",
            "answer": content or "当前报告中该问题的信息有限，建议查看来源文件或换一个问法。",
            "evidence_refs": matched.get("evidence_refs", [])[:3],
            "finance_agent_handoff": None,
            "suggested_questions": _suggested_questions(),
        }

    def finance_handoff(self, report_id: str, user_question: str = "") -> dict:
        return self._finance_handoff(self.get_report(report_id), user_question)

    def _select_report(self, company: dict, year: Optional[int]) -> dict:
        reports = self.ashare_source.list_reports(company)
        annual = [item for item in reports if item["report_type"] == "annual"]
        if year:
            target = f"{year}-FY"
            annual = [item for item in annual if item["period"] == target]
        if not annual:
            raise ValueError("暂未找到可用年度报告。")
        return annual[0]

    def _select_prospectus(self, company: dict) -> dict:
        documents = self.ashare_source.cninfo.list_prospectuses(company)
        if not documents:
            raise ValueError("暂未在巨潮资讯找到可用招股说明书。")
        return documents[0]

    def _select_document(self, company: dict, document_type: str, year: Optional[int]) -> dict:
        normalized = _normalize_document_type(document_type)
        if normalized == "prospectus":
            return self._select_prospectus(company)
        if normalized == "annual_report":
            return self._select_report(company, year)
        try:
            return self._select_report(company, year)
        except Exception:
            return self._select_prospectus(company)

    def _build_report(self, company: dict, document: dict, parsed: dict, report_style: str, llm_profile: Optional[dict] = None) -> dict:
        report_id = _id("profile_report")
        evidence_factory = EvidenceFactory(self.evidences, company, document, parsed)
        profile = _extract_profile(company, parsed, evidence_factory, llm_profile=llm_profile)
        sections = _build_sections(profile, evidence_factory, document)
        finance_context_id = _id("profile_finance_handoff")
        return {
            "report_id": report_id,
            "title": f"一页看懂：{company['name']}",
            "company": _company_payload(company),
            "source_document": _document_payload(document),
            "report_type": report_style,
            "extraction_mode": "llm" if llm_profile else "rule_fallback",
            "sections": sections,
            "finance_agent_entry": {
                "enabled": True,
                "handoff_context_id": finance_context_id,
                "target_url": f"/index.html?ticker={company['ticker']}&market=CN",
            },
            "suggested_questions": _suggested_questions(),
            "disclaimer": "本报告仅基于公开披露文件自动生成，用于帮助理解公司，不构成投资建议。",
            "created_at": _now(),
        }

    def _finance_handoff(self, report: dict, user_question: str) -> dict:
        company = report["company"]
        document = report["source_document"]
        return {
            "handoff_context_id": report["finance_agent_entry"]["handoff_context_id"],
            "target_agent": "financial_report_agent",
            "target_url": f"/index.html?ticker={company['stock_code']}&market=CN",
            "context": {
                "company_name": company["full_name"],
                "stock_code": company["stock_code"],
                "market": company["market"],
                "exchange": company["exchange"],
                "document_type": document["document_type"],
                "document_name": document["document_title"],
                "report_period": document["report_period"],
                "disclosure_date": document["disclosure_date"],
                "source_platform": document["source_platform"],
                "source_url": document["source_url"],
                "current_user_question": user_question,
            },
        }

    def _task(self, task_id: str, query: str, status: str, progress: int, step: str) -> dict:
        return {
            "task_id": task_id,
            "user_query": query,
            "status": status,
            "progress": progress,
            "current_step": step,
            "company": None,
            "document": None,
            "report_id": None,
            "error": None,
            "candidates": [],
            "created_at": _now(),
            "updated_at": _now(),
        }


class EvidenceFactory:
    def __init__(self, store: Dict[str, dict], company: dict, document: dict, parsed: dict):
        self.store = store
        self.company = company
        self.document = document
        self.parsed = parsed

    def create(self, claim_type: str, claim: str, section_key: str, keywords: List[str], confidence: str = "MEDIUM") -> str:
        block = _find_block(self.parsed["blocks"], keywords) or _find_block(self.parsed["blocks"], [section_key]) or self.parsed["blocks"][0]
        evidence_id = _id("ev")
        item = {
            "evidence_id": evidence_id,
            "company_id": self.company["id"],
            "document_id": self.document["id"],
            "claim_type": claim_type,
            "claim": claim,
            "source": _document_payload(self.document),
            "location": {
                "page": block["page"],
                "section_title": block.get("section_title") or section_key,
                "text_block_id": block["id"],
            },
            "original_text": _trim(block["text"], 420),
            "confidence": confidence,
            "extraction_method": "SUMMARIZED",
        }
        self.store[evidence_id] = item
        return evidence_id


def _parse_document_text(text: str) -> dict:
    pages = [page.strip() for page in text.split("\n\n") if page.strip()]
    if len(pages) <= 1:
        pages = [part.strip() for part in re.split(r"\n(?=\d{1,3}\s*$)", text) if part.strip()]
    blocks = []
    for idx, page_text in enumerate(pages[:120], start=1):
        clean = re.sub(r"\s+", " ", page_text).strip()
        if not clean:
            continue
        blocks.append({"id": f"txt_{idx:03d}", "page": idx, "section_title": _guess_section(clean), "text": clean})
    if not blocks:
        blocks = [{"id": "txt_001", "page": 1, "section_title": "全文", "text": _trim(text, 2000)}]
    return {"blocks": blocks, "text": "\n".join(block["text"] for block in blocks), "parse_quality": "MEDIUM"}


def _extract_profile(company: dict, parsed: dict, evidence_factory: EvidenceFactory, llm_profile: Optional[dict] = None) -> dict:
    text = parsed["text"]
    llm_profile = llm_profile or {}
    main_business = _llm_text(llm_profile, "business_summary") or _extract_after(text, ["主营业务", "主要业务", "公司主要从事"], max_len=180) or "文件中披露了公司的主营业务，但当前版本未能稳定抽取完整表述。"
    industry = _llm_text(llm_profile, "industry") or _extract_after(text, ["所属行业", "行业分类"], max_len=80) or company.get("industry") or "文件未披露"
    controller = _llm_text(llm_profile, "actual_controller") or _extract_after(text, ["实际控制人"], max_len=60) or "文件未披露或当前版本未能识别"
    shareholder = _llm_text(llm_profile, "controlling_shareholder") or _extract_after(text, ["控股股东"], max_len=60) or controller
    risks = _extract_risks(text)
    business_ev = evidence_factory.create("business_model", main_business, "主营业务", ["主营业务", "主要业务", "公司主要从事"])
    ownership_ev = evidence_factory.create("ownership", shareholder, "股东与控制权", ["控股股东", "实际控制人", "前十名股东"])
    risk_ev = evidence_factory.create("non_financial_risk", "非财务风险提示", "风险因素", ["风险", "客户", "供应商", "技术", "诉讼", "处罚"])
    capital_ev = evidence_factory.create("capital_actions", "资本动作", "利润分配与资本动作", ["分红", "回购", "股权激励", "募集资金", "增持", "减持"])
    people_ev = evidence_factory.create("key_people", "关键人物", "董事监事高级管理人员", ["董事", "监事", "高级管理人员", "核心技术人员"])
    chain_ev = evidence_factory.create("industry_chain", "产业链", "业务与上下游", ["供应商", "客户", "采购", "销售", "上游", "下游"])
    llm_people = _llm_people(llm_profile.get("key_people"), people_ev)
    llm_chain = llm_profile.get("industry_chain") if isinstance(llm_profile.get("industry_chain"), dict) else {}
    llm_capital = llm_profile.get("capital_actions") if isinstance(llm_profile.get("capital_actions"), dict) else {}
    llm_risks = _llm_risks(llm_profile.get("non_financial_risks"), risk_ev)
    return {
        "company_profile": {
            "full_name": company["name"],
            "short_name": company.get("short_name") or company["name"],
            "stock_code": company["ticker"],
            "market": "CN_A",
            "exchange": company.get("exchange"),
            "industry": industry,
            "main_business": main_business,
            "controlling_shareholder": shareholder,
            "actual_controller": controller,
            "evidence_refs": [business_ev, ownership_ev],
        },
        "business_model": {
            "business_summary": main_business,
            "business_segments": [
                {
                    "name": "主营业务",
                    "core_products_or_services": _extract_products(main_business),
                    "revenue_source_description": "公司通过披露文件所述主营业务、产品或服务获得收入。本模块只解释收入来源，不分析收入规模或增长。",
                    "plain_explanation": _plain_business(company["name"], main_business),
                    "evidence_refs": [business_ev],
                }
            ],
            "evidence_refs": [business_ev],
        },
        "ownership": {
            "controlling_shareholder": shareholder,
            "actual_controller": controller,
            "control_type": _control_type(controller, shareholder),
            "shareholders": [],
            "ownership_tags": _ownership_tags(controller, shareholder),
            "plain_explanation": _plain_ownership(controller, shareholder),
            "evidence_refs": [ownership_ev],
        },
        "key_people": llm_people or _extract_people(text, people_ev),
        "industry_chain": {
            "upstream": _llm_list(llm_chain.get("upstream")) or _keyword_items(text, ["供应商", "原材料", "采购"]),
            "company_position": main_business,
            "downstream": _llm_list(llm_chain.get("downstream")) or _keyword_items(text, ["客户", "销售", "终端"]),
            "end_users": [],
            "major_customers": _llm_list(llm_chain.get("major_customers")),
            "major_suppliers": _llm_list(llm_chain.get("major_suppliers")),
            "bargaining_power_note": "V1 仅基于披露文件做普通解释，不进行财务或竞争力评级。",
            "risk_note": "如文件披露客户或供应商集中，建议重点查看风险章节。",
            "evidence_refs": [chain_ev],
        },
        "capital_actions": {
            "dividends": _contains_items(text, ["分红", "利润分配"]),
            "buybacks": _contains_items(text, ["回购"]),
            "equity_incentives": _contains_items(text, ["股权激励"]),
            "financing_actions": _contains_items(text, ["可转债", "定增", "募集资金", "发行"]),
            "summary": _llm_text(llm_capital, "summary") or "本模块只说明披露文件中的资本动作，不判断分红率、资金压力或财务质量。",
            "evidence_refs": [capital_ev],
        },
        "non_financial_risks": llm_risks or [
            {
                "risk_name": item,
                "risk_type": item,
                "severity": "medium",
                "plain_explanation": _risk_plain(item),
                "evidence_refs": [risk_ev],
            }
            for item in risks
        ],
        "evidence_refs": [business_ev, ownership_ev, people_ev, chain_ev, capital_ev, risk_ev],
    }


def _build_sections(profile: dict, evidence_factory: EvidenceFactory, document: dict) -> List[dict]:
    cp = profile["company_profile"]
    bm = profile["business_model"]
    own = profile["ownership"]
    risks = profile["non_financial_risks"] or []
    conclusion = (
        f"{cp['short_name']}是一家披露文件显示主要围绕“{_trim(cp['main_business'], 80)}”开展经营的公司。"
        f"从公司画像角度，建议重点看业务模式、控制权结构、关键人物、上下游关系和非财务风险。"
    )
    return [
        _section("source_document", "本次使用的资料", [{"type": "notice", "text": _source_notice(document)}], []),
        _section("one_sentence_summary", "一句话看懂", [{"type": "paragraph", "text": _plain_business(cp["short_name"], cp["main_business"])}], bm["evidence_refs"]),
        _section("basic_info", "基本信息", [{"type": "kv", "items": cp}], cp["evidence_refs"]),
        _section("business_model", "业务与收入来源", [{"type": "paragraph", "text": bm["business_summary"]}, {"type": "table", "rows": bm["business_segments"]}], bm["evidence_refs"]),
        _section("ownership", "股东与控制权", [{"type": "paragraph", "text": own["plain_explanation"]}, {"type": "kv", "items": own}], own["evidence_refs"]),
        _section("key_people", "关键少数人", [{"type": "cards", "items": profile["key_people"]}], [ref for person in profile["key_people"] for ref in person.get("evidence_refs", [])]),
        _section("industry_chain", "上下游产业链", [{"type": "kv", "items": profile["industry_chain"]}], profile["industry_chain"]["evidence_refs"]),
        _section("capital_actions", "融资、分红与资本动作", [{"type": "kv", "items": profile["capital_actions"]}], profile["capital_actions"]["evidence_refs"]),
        _section("non_financial_risks", "非财务风险红旗", [{"type": "risk_cards", "items": risks}], [ref for risk in risks for ref in risk.get("evidence_refs", [])]),
        _section("plain_conclusion", "普通人版结论", [{"type": "paragraph", "text": conclusion}], profile["evidence_refs"][:3]),
        _section("finance_agent_entry", "财务 Agent 入口", [{"type": "notice", "text": "想进一步看收入增长、利润率、现金流、资产负债和财务风险，可进入财报掘金继续分析。"}], []),
        _section("follow_up_questions", "继续追问", [{"type": "questions", "items": _suggested_questions()}], []),
    ]


def _section(section_type: str, title: str, blocks: List[dict], refs: List[str]) -> dict:
    return {"section_id": _id("profile_sec"), "section_type": section_type, "title": title, "content_blocks": blocks, "evidence_refs": refs}


def _company_payload(company: dict) -> dict:
    return {
        "company_id": company["id"],
        "full_name": company["name"],
        "short_name": company.get("short_name") or company["name"],
        "stock_code": company["ticker"],
        "market": "CN_A",
        "exchange": company.get("exchange"),
    }


def _document_payload(document: dict) -> dict:
    return {
        "document_id": document["id"],
        "document_type": "annual_report" if document["report_type"] == "annual" else document["report_type"],
        "document_title": document.get("title") or document["period"],
        "report_period": document["period"],
        "disclosure_date": document.get("publish_date"),
        "source_platform": "CNINFO",
        "source_url": document.get("source_url"),
        "version_type": "OFFICIAL",
        "parse_status": "SUCCESS",
        "information_completeness": "MEDIUM",
    }


def _normalize_document_type(document_type: str) -> str:
    value = (document_type or "auto").strip().lower()
    if value in {"prospectus", "ipo", "zgsms", "招股书", "招股说明书"}:
        return "prospectus"
    if value in {"annual", "annual_report", "year", "年报", "年度报告"}:
        return "annual_report"
    return "auto"


def _detect_document_type(query: str, document_type: str) -> str:
    normalized = _normalize_document_type(document_type)
    if normalized != "auto":
        return normalized
    if any(word in query for word in ["招股", "IPO", "ipo", "上市申请", "发行上市"]):
        return "prospectus"
    if any(word in query for word in ["年报", "年度报告"]):
        return "annual_report"
    return "auto"


def _detect_year(query: str) -> Optional[int]:
    match = re.search(r"(20\d{2})\s*年?", query or "")
    if not match:
        return None
    return int(match.group(1))


def _clean_company_query(query: str) -> str:
    value = (query or "").strip()
    value = re.sub(r"(20\d{2})\s*年?", "", value)
    for word in ["帮我看一下", "看一下", "分析", "公司画像", "一页看懂", "招股说明书", "招股书", "年度报告", "年报"]:
        value = value.replace(word, "")
    value = re.sub(r"\s*的\s*$", "", value)
    return value.strip(" ，,。")


def _retrieving_step(document_type: str) -> str:
    if _normalize_document_type(document_type) == "prospectus":
        return "正在查找招股说明书"
    if _normalize_document_type(document_type) == "annual_report":
        return "正在查找年度报告"
    return "正在查找公开披露文件"


def _document_kind_name(document: dict) -> str:
    if document.get("report_type") == "prospectus":
        return "招股说明书"
    return "年度报告"


def _source_notice(document: dict) -> str:
    kind = "招股说明书" if document.get("report_type") == "prospectus" else "年度报告"
    return f"以下内容仅基于公司公开披露的{kind}生成，未引入新闻、研报、社区评论或第三方观点。"


def _normalize_market(query: str, market: str) -> str:
    value = (market or "auto").upper()
    if value in {"CN", "A", "CN_A"}:
        return "CN"
    if value == "AUTO" and re.search(r"\d{6}", query):
        return "CN"
    if value == "AUTO" and re.search(r"[\u4e00-\u9fa5]", query):
        return "CN"
    return value


def _extract_after(text: str, keywords: List[str], max_len: int) -> str:
    for keyword in keywords:
        match = re.search(rf"{re.escape(keyword)}[：:，,。\s]*(.{{8,{max_len}}})", text)
        if match:
            return _clean_sentence(match.group(1), max_len)
    return ""


def _extract_risks(text: str) -> List[str]:
    candidates = [
        ("客户集中风险", ["客户集中", "主要客户"]),
        ("供应商集中风险", ["供应商集中", "主要供应商"]),
        ("原材料价格波动风险", ["原材料价格", "价格波动"]),
        ("技术替代风险", ["技术替代", "技术路线"]),
        ("合规与诉讼风险", ["诉讼", "处罚", "合规"]),
        ("海外业务风险", ["海外", "汇率", "国际"]),
        ("控制权风险", ["实际控制人", "控制权", "股权质押"]),
    ]
    hits = [name for name, words in candidates if any(word in text for word in words)]
    return hits[:5] or ["披露信息完整性风险"]


def _extract_products(text: str) -> List[str]:
    products = re.split(r"[、，,；;和及]", text)
    return [_trim(item, 18) for item in products if 2 <= len(item.strip()) <= 18][:6]


def _extract_people(text: str, evidence_ref: str) -> List[dict]:
    names = []
    for pattern in [r"董事长[：:\s]*([\u4e00-\u9fa5]{2,4})", r"总经理[：:\s]*([\u4e00-\u9fa5]{2,4})", r"实际控制人[：:\s]*([\u4e00-\u9fa5]{2,4})"]:
        for match in re.finditer(pattern, text):
            if match.group(1) not in names:
                names.append(match.group(1))
    if not names:
        return [{"name": "文件披露的董监高团队", "role": "管理团队", "background": "V1 未稳定识别具体履历", "importance_reason": "管理团队影响公司经营和治理。", "tags": ["管理团队"], "evidence_refs": [evidence_ref]}]
    return [
        {"name": name, "role": "关键人物", "background": "详见年报董监高或实际控制人章节。", "importance_reason": "该人物在披露文件中与公司治理或经营管理相关。", "tags": ["关键人物"], "evidence_refs": [evidence_ref]}
        for name in names[:5]
    ]


def _llm_text(payload: dict, key: str) -> str:
    if not isinstance(payload, dict):
        return ""
    value = payload.get(key)
    if not isinstance(value, str):
        return ""
    value = _trim(value, 260)
    return "" if value in {"未知", "无", "未披露", "不详"} else value


def _llm_list(value) -> List[str]:
    if not isinstance(value, list):
        return []
    items = []
    for item in value:
        text = _trim(item, 40)
        if text and text not in items and text not in {"未知", "未披露", "不详"}:
            items.append(text)
    return items[:8]


def _llm_people(value, evidence_ref: str) -> List[dict]:
    if not isinstance(value, list):
        return []
    people = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = _trim(item.get("name"), 20)
        if not name or name in {"未知", "未披露", "管理团队"}:
            continue
        people.append(
            {
                "name": name,
                "role": _trim(item.get("role"), 40) or "关键人物",
                "background": _trim(item.get("background"), 180) or "文件披露了该人物履历，当前模型未提炼完整摘要。",
                "importance_reason": _trim(item.get("importance_reason"), 160) or "该人物在披露文件中与公司治理、核心技术或经营管理相关。",
                "tags": _llm_list(item.get("tags")) or ["关键人物"],
                "evidence_refs": [evidence_ref],
            }
        )
    return people[:6]


def _llm_risks(value, evidence_ref: str) -> List[dict]:
    if not isinstance(value, list):
        return []
    risks = []
    for item in value:
        if not isinstance(item, dict):
            continue
        risk_name = _trim(item.get("risk_name"), 40)
        if not risk_name:
            continue
        severity = str(item.get("severity") or "medium").lower()
        if severity not in {"high", "medium", "low"}:
            severity = "medium"
        risks.append(
            {
                "risk_name": risk_name,
                "risk_type": _trim(item.get("risk_type"), 40) or risk_name,
                "severity": severity,
                "plain_explanation": _trim(item.get("plain_explanation"), 180) or _risk_plain(risk_name),
                "evidence_refs": [evidence_ref],
            }
        )
    return risks[:6]


def _keyword_items(text: str, keywords: List[str]) -> List[str]:
    items = []
    for keyword in keywords:
        if keyword in text:
            items.append(keyword)
    return items[:5] or ["文件未稳定披露或 V1 未识别"]


def _contains_items(text: str, keywords: List[str]) -> List[dict]:
    return [{"name": keyword, "status": "有披露", "plain_explanation": f"披露文件中出现“{keyword}”相关内容。"} for keyword in keywords if keyword in text] or [{"name": "未稳定识别", "status": "未披露或未识别", "plain_explanation": "当前版本未在披露文件中稳定识别该类资本动作。"}]


def _find_block(blocks: List[dict], keywords: List[str]) -> Optional[dict]:
    for block in blocks:
        if any(keyword and keyword in block["text"] for keyword in keywords):
            return block
    return None


def _guess_section(text: str) -> str:
    for key in ["主营业务", "公司简介", "股东", "董事", "客户", "供应商", "风险", "分红", "募集资金"]:
        if key in text:
            return key
    return "年报正文"


def _plain_business(name: str, business: str) -> str:
    return f"{name}主要围绕“{_trim(business, 90)}”开展业务。普通人可以理解为，公司通过披露文件中的核心产品或服务向客户提供价值并获得收入。"


def _plain_ownership(controller: str, shareholder: str) -> str:
    if "未披露" in controller and "未披露" in shareholder:
        return "当前版本未能从年报中稳定识别控股股东或实际控制人，建议查看证据原文。"
    return f"公司披露的控股股东或实际控制人信息显示，{_trim(shareholder or controller, 80)}对公司治理具有重要影响。"


def _control_type(controller: str, shareholder: str) -> str:
    text = f"{controller}{shareholder}"
    if "国资" in text or "国有" in text:
        return "state_owned_or_state_related"
    if "无实际控制人" in text:
        return "no_actual_controller"
    if "未披露" in text:
        return "unknown"
    return "controlled"


def _ownership_tags(controller: str, shareholder: str) -> List[str]:
    text = f"{controller}{shareholder}"
    tags = []
    if "国资" in text or "国有" in text:
        tags.append("国资背景")
    if "无实际控制人" in text:
        tags.append("无实际控制人")
    if not tags:
        tags.append("控制权待进一步核验")
    return tags


def _risk_plain(risk: str) -> str:
    mapping = {
        "客户集中风险": "如果主要客户减少订单，公司业务稳定性可能受到影响。",
        "供应商集中风险": "如果关键供应商供货或价格发生变化，公司经营可能受到影响。",
        "原材料价格波动风险": "上游原材料涨价可能影响公司产品成本和交付。",
        "技术替代风险": "如果行业技术路线变化，公司现有产品或服务可能面临替代压力。",
        "合规与诉讼风险": "诉讼、处罚或合规问题可能影响公司声誉和经营连续性。",
        "海外业务风险": "海外业务可能受到汇率、政策和国际环境影响。",
        "控制权风险": "控制权变化或过度集中可能影响公司重大决策。",
    }
    return mapping.get(risk, "披露文件信息有限，需要结合来源原文继续核验。")


def _section_for_question(lower: str, question: str) -> str:
    if any(word in question for word in ["业务", "收入", "产品", "服务", "靠什么"]):
        return "business_model"
    if any(word in question for word in ["股东", "控制", "实控人", "谁说了算"]):
        return "ownership"
    if any(word in question for word in ["人物", "高管", "董事长", "管理层"]):
        return "key_people"
    if any(word in question for word in ["上游", "下游", "客户", "供应商", "产业链"]):
        return "industry_chain"
    if any(word in question for word in ["风险", "红旗"]):
        return "non_financial_risks"
    if any(word in question for word in ["分红", "回购", "融资", "募资", "资本"]):
        return "capital_actions"
    return "plain_conclusion"


def _section_text(section: dict) -> str:
    texts = []
    for block in section.get("content_blocks", []):
        if block.get("type") in {"paragraph", "notice"}:
            texts.append(block.get("text", ""))
        elif block.get("type") == "kv":
            texts.extend([f"{key}：{value}" for key, value in block.get("items", {}).items() if isinstance(value, (str, int, float))])
    return " ".join(texts)


def _is_financial_question(question: str) -> bool:
    lower = question.lower()
    return any(term in lower or term in question for term in FINANCIAL_TERMS)


def _suggested_questions() -> List[str]:
    return ["这家公司到底靠什么业务获得收入？", "谁真正控制这家公司？", "它的上游和下游分别是谁？", "有哪些非财务风险？", "有哪些资本动作？"]


def _clean_sentence(text: str, max_len: int) -> str:
    text = re.split(r"[。；\n]", text.strip())[0]
    return _trim(text, max_len)


def _trim(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")
