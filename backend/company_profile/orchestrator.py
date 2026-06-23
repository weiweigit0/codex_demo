from __future__ import annotations

import re
import time
import uuid
from pathlib import Path
from threading import RLock, Thread
from typing import Dict, List, Optional

from backend.company_profile.agent import CompanyProfileAgent
from backend.company_profile.document_segmenter import DocumentSegmenter
from backend.company_profile.evidence_service import EvidenceService
from backend.data_platform.service import DataService
from backend.repositories.json_store import JsonStore


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
    def __init__(self, data_service: DataService):
        self.data_service = data_service
        self.segmenter = DocumentSegmenter()
        self.profile_agent = CompanyProfileAgent(segmenter=self.segmenter)
        self.store = JsonStore(Path(__file__).resolve().parents[1] / "storage")
        self.tasks: Dict[str, dict] = {item["task_id"]: item for item in self.store.list("profile_tasks") if item.get("task_id")}
        self.reports: Dict[str, dict] = {item["report_id"]: item for item in self.store.list("profile_reports") if item.get("report_id")}
        self.evidences: Dict[str, dict] = {item["evidence_id"]: item for item in self.store.list("profile_evidences") if item.get("evidence_id")}
        self._lock = RLock()

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
        self.store.upsert("profile_tasks", task_id, task)
        Thread(
            target=self._generate_report,
            args=(task, query, market, document_type, year, report_style),
            daemon=True,
        ).start()
        return task

    def _generate_report(self, task: dict, query: str, market: str, document_type: str, year: Optional[int], report_style: str) -> None:
        try:
            resolved_year = year or _detect_year(query)
            company_query = _clean_company_query(query)
            normalized_market = _normalize_market(company_query or query, market)
            if normalized_market not in {"CN", "US"}:
                raise ValueError("暂不支持该市场的公司画像。")

            company = self._resolve_company(company_query or query, normalized_market)
            task.update(
                {
                    "status": "RETRIEVING_DOCUMENT",
                    "progress": 25,
                    "current_step": "正在收集招股书与最近三年年报",
                    "company": company,
                }
            )
            documents = self._select_profile_documents(company, resolved_year)
            report_meta = documents[0]
            task.update({"status": "PARSING_DOCUMENT", "progress": 55, "current_step": "正在解析披露文件资料包", "document": report_meta})
            parsed = self._parse_documents(documents)
            encyclopedia_context = self.data_service.get_encyclopedia(company)
            cache_key = self.data_service.profile_cache_key(
                company, documents, encyclopedia_context, "company_profile_agent_v2_risk_split"
            )

            task.update({"status": "EXTRACTING_INFORMATION", "progress": 75, "current_step": "正在由公司画像 Agent 抽取结构化信息"})
            cached = self.data_service.get_profile_cache(cache_key)
            if cached:
                report = cached["report"]
                for evidence_id, item in cached.get("evidences", {}).items():
                    self.evidences[evidence_id] = item
                    self.store.upsert("profile_evidences", evidence_id, item)
                report.setdefault("generation_meta", {})["cache_status"] = "HIT"
            else:
                evidence_ids_before = set(self.evidences)
                report = self._build_report(company, report_meta, parsed, report_style, documents, encyclopedia_context)
                evidence_items = {key: value for key, value in self.evidences.items() if key not in evidence_ids_before}
                self.data_service.save_profile_cache(
                    company,
                    cache_key,
                    {"report": report, "evidences": evidence_items},
                    "company_profile_agent_v2_risk_split",
                )

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
            self.store.upsert("profile_reports", report["report_id"], report)
        except Exception as exc:
            task.update(
                {
                    "status": "FAILED_REPORT_GENERATION",
                    "progress": task.get("progress", 0),
                    "current_step": "公司画像生成失败",
                    "error": {"code": "REPORT_GENERATION_FAILED", "message": _public_error_message(exc)},
                    "updated_at": _now(),
                }
            )
        finally:
            self.store.upsert("profile_tasks", task["task_id"], task)

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

    def _resolve_company(self, query: str, market: str) -> dict:
        return self.data_service.resolve_company(query, market)

    def _select_profile_documents(self, company: dict, year: Optional[int]) -> List[dict]:
        documents = self.data_service.list_profile_documents(company, year)
        if not documents:
            raise ValueError("暂未找到可用的年报或招股说明书。")
        return documents

    def _parse_documents(self, documents: List[dict]) -> dict:
        blocks = []
        for document in documents:
            canonical_blocks = self.data_service.canonical_document_blocks(document)
            for block in canonical_blocks:
                if block.get("content_type") != "paragraph":
                    continue
                blocks.append({
                    "id": block["block_id"],
                    "page": block.get("page_number") or 1,
                    "section_title": block.get("section_title") or "披露文件正文",
                    "groups": self.segmenter.classify(block.get("text", "")),
                    "text": block.get("text", ""),
                    "document": document,
                })
        if not blocks:
            raise ValueError("披露文件未能解析出可用文本。")
        return {"blocks": blocks, "text": "\n".join(block["text"] for block in blocks), "parse_quality": "MEDIUM"}

    def _build_report(self, company: dict, document: dict, parsed: dict, report_style: str, documents: List[dict], encyclopedia_context: Optional[dict] = None) -> dict:
        report_id = _id("profile_report")
        evidence_service = EvidenceService(self.evidences, company, document, parsed, _document_payload)
        if encyclopedia_context:
            parsed["blocks"].append(
                {
                    "id": "encyclopedia_001",
                    "page": "百科",
                    "section_title": encyclopedia_context["source_type"],
                    "groups": ["basic_info"],
                    "text": encyclopedia_context["summary"],
                    "document": {
                        "id": "ENC-%s" % company["ticker"],
                        "report_type": "encyclopedia",
                        "period": "reference",
                        "publish_date": None,
                        "source_url": encyclopedia_context.get("url"),
                        "title": encyclopedia_context.get("title"),
                        "source_platform": encyclopedia_context["source_type"],
                    },
                }
            )
        agent_result = self.profile_agent.generate_two_stage(company, document, parsed, evidence_service)
        for evidence_id, item in self.evidences.items():
            self.store.upsert("profile_evidences", evidence_id, item)
        profile = agent_result.profile.dict()
        self.data_service.persist_company_facts(company, profile, self.evidences, agent_result.generation_meta.get("agent_version", "company_profile_agent"))
        sections = _build_sections(profile, document, agent_result.generation_meta, agent_result.risk_facts, agent_result.risk_assessments)
        finance_context_id = _id("profile_finance_handoff")
        return {
            "report_id": report_id,
            "title": f"一页看懂：{company['name']}",
            "company": _company_payload(company),
            "source_document": _document_payload(document),
            "source_documents": [_document_payload(item) for item in documents],
            "report_type": report_style,
            "extraction_mode": agent_result.generation_meta.get("extraction_mode", "agent_llm"),
            "generation_meta": agent_result.generation_meta,
            "risk_facts": agent_result.risk_facts,
            "risk_assessments": agent_result.risk_assessments,
            "sections": sections,
            "finance_agent_entry": {
                "enabled": True,
                "handoff_context_id": finance_context_id,
                "target_url": f"/index.html?ticker={company['ticker']}&market={company.get('market', 'CN')}",
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
            "target_url": f"/index.html?ticker={company['stock_code']}&market={company.get('market', 'CN')}",
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

def _build_sections(profile: dict, document: dict, generation_meta: Optional[dict] = None, risk_facts: Optional[List[dict]] = None, risk_assessments: Optional[List[dict]] = None) -> List[dict]:
    cp = profile["company_profile"]
    bm = profile["business_model"]
    own = profile["ownership"]
    risks = profile["non_financial_risks"] or []
    missing = profile.get("missing_information") or []
    conclusion = (
        f"{cp['short_name']}是一家披露文件显示主要围绕“{_trim(cp['main_business'], 80)}”开展经营的公司。"
        f"从公司画像角度，建议重点看业务模式、控制权结构、关键人物、上下游关系和非财务风险。"
    )
    return [
        _section("source_document", "本次使用的资料", [{"type": "notice", "text": _source_notice(document, bool((generation_meta or {}).get("used_wikipedia")))}], []),
        _section("one_sentence_summary", "一句话看懂", [{"type": "paragraph", "text": _plain_business(cp["short_name"], cp["main_business"])}], bm["evidence_refs"]),
        _section("basic_info", "基本信息", [{"type": "kv", "items": cp}], cp["evidence_refs"]),
        _section("business_model", "业务与收入来源", [{"type": "paragraph", "text": bm["business_summary"]}, {"type": "table", "rows": bm["business_segments"]}], bm["evidence_refs"]),
        _section("ownership", "股东与控制权", [{"type": "paragraph", "text": own["plain_explanation"]}, {"type": "kv", "items": own}], own["evidence_refs"]),
        _section("key_people", "关键少数人", [{"type": "cards", "items": profile["key_people"]}], [ref for person in profile["key_people"] for ref in person.get("evidence_refs", [])]),
        _section("industry_chain", "上下游产业链", [{"type": "kv", "items": profile["industry_chain"]}], profile["industry_chain"]["evidence_refs"]),
        _section("capital_actions", "融资、分红与资本动作", [{"type": "kv", "items": profile["capital_actions"]}], profile["capital_actions"]["evidence_refs"]),
        _section("non_financial_risks", "风险事实与需关注程度", [{"type": "risk_facts", "items": risk_facts or []}, {"type": "risk_assessments", "items": risk_assessments or []}], [ref for fact in (risk_facts or []) for ref in fact.get("evidence_refs", [])]),
        _section("plain_conclusion", "普通人版结论", [{"type": "paragraph", "text": conclusion}], profile["evidence_refs"][:3]),
        _section("missing_information", "缺失与待核验信息", [{"type": "kv", "items": _missing_items(missing)}], profile["evidence_refs"][:1]),
        _section("finance_agent_entry", "财务 Agent 入口", [{"type": "notice", "text": "想进一步看收入增长、利润率、现金流、资产负债和财务风险，可进入财报掘金继续分析。"}], []),
        _section("follow_up_questions", "继续追问", [{"type": "questions", "items": _suggested_questions()}], []),
    ]


def _section(section_type: str, title: str, blocks: List[dict], refs: List[str]) -> dict:
    return {"section_id": _id("profile_sec"), "section_type": section_type, "title": title, "content_blocks": blocks, "evidence_refs": refs}


def _missing_items(items: List[dict]) -> dict:
    if not items:
        return {"status": "暂无缺失信息", "note": "公司画像 Agent 未返回需要额外核验的字段。"}
    return {
        "item_%d" % (idx + 1): "%s：%s（建议来源：%s）" % (
            item.get("field") or "未知字段",
            item.get("reason") or "信息不足",
            item.get("suggested_source") or "公开披露文件",
        )
        for idx, item in enumerate(items[:8])
    }


def _company_payload(company: dict) -> dict:
    return {
        "company_id": company["id"],
        "full_name": company["name"],
        "short_name": company.get("short_name") or company["name"],
        "stock_code": company["ticker"],
        "market": "CN_A" if company.get("market") == "CN" else "US",
        "exchange": company.get("exchange"),
    }


def _document_payload(document: dict) -> dict:
    return {
        "document_id": document["id"],
        "document_type": "annual_report" if document["report_type"] == "annual" else document["report_type"],
        "document_title": document.get("title") or document["period"],
        "report_period": document["period"],
        "disclosure_date": document.get("publish_date"),
        "source_platform": document.get("source_platform") or "CNINFO",
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


def _source_notice(document: dict, used_wikipedia: bool = False) -> str:
    kind = "招股说明书" if document.get("report_type") == "prospectus" else "年度报告"
    if used_wikipedia:
        return f"以下内容优先基于公司公开披露的{kind}生成，仅允许维基百科补充基础背景；未引入新闻、研报、社区评论或投资观点。"
    return f"以下内容仅基于公司公开披露的{kind}生成，未引入新闻、研报、社区评论或第三方观点。"


def _normalize_market(query: str, market: str) -> str:
    value = (market or "auto").upper()
    if value in {"CN", "A", "CN_A"}:
        return "CN"
    if value == "AUTO" and re.search(r"\d{6}", query):
        return "CN"
    if value == "AUTO" and re.search(r"[\u4e00-\u9fa5]", query):
        return "CN"
    return "US" if value == "AUTO" else value


def _sec_source_for_record(record: dict, filings: dict) -> Optional[dict]:
    for accession in record.get("sources") or []:
        filing = filings.get(accession)
        if filing and filing.get("form") in {"10-K", "20-F", "10-Q", "6-K"}:
            return filing
    return None


def _plain_business(name: str, business: str) -> str:
    if not business or business == "未披露":
        return f"{name}的主营业务在当前结构化结果中未能确认，建议查看缺失与待核验信息。"
    return f"{name}主要围绕“{_trim(business, 90)}”开展业务。普通人可以理解为，公司通过披露文件中的核心产品或服务向客户提供价值。"


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


def _trim(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _public_error_message(exc: Exception) -> str:
    if isinstance(exc, ValueError):
        return str(exc)
    return "披露文件、网络或模型服务暂时不可用，请稍后重试。"
