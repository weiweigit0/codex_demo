from __future__ import annotations

import uuid
from pathlib import Path
from threading import RLock, Thread

from backend.data_platform.repository import json_hash, utc_now
from backend.financial_agent.agent import FinancialAnalysisAgent, PROMPT_VERSION
from backend.repositories.json_store import JsonStore
from backend.services.analysis_engine import analyze_periods


class FinancialAnalysisOrchestrator:
    def __init__(self, data_service):
        self.data_service = data_service
        self.agent = FinancialAnalysisAgent()
        self.store = JsonStore(Path(__file__).resolve().parents[1] / "storage")
        self.tasks = {item["task_id"]: item for item in self.store.list("financial_agent_tasks") if item.get("task_id")}
        self.analyses = {item["analysis_id"]: item for item in self.store.list("financial_agent_analyses") if item.get("analysis_id")}
        self._lock = RLock()

    def create_analysis(self, ticker: str, market: str, periods: list[str], period_type: str, include_peer_context: bool = False) -> dict:
        task_id = "financial_task_%s" % uuid.uuid4().hex[:16]
        task = self._task(task_id, ticker, market, periods, period_type)
        self.tasks[task_id] = task
        self.store.upsert("financial_agent_tasks", task_id, task)
        Thread(target=self._run, args=(task, ticker, market, periods, period_type, include_peer_context), daemon=True).start()
        return task

    def get_task(self, task_id: str) -> dict:
        if task_id not in self.tasks:
            raise KeyError("任务不存在")
        return self.tasks[task_id]

    def get_analysis(self, analysis_id: str) -> dict:
        if analysis_id not in self.analyses:
            raise KeyError("分析结果不存在")
        return self.analyses[analysis_id]

    def _run(self, task: dict, ticker: str, market: str, periods: list[str], period_type: str, include_peer_context: bool) -> None:
        run_id = "financial_run_%s" % uuid.uuid4().hex[:16]
        try:
            company = self.data_service.resolve_company(ticker, market)
            task.update({"status": "VALIDATING_DATA", "progress": 15, "current_step": "正在校验财务事实", "company": company})
            dataset = self.data_service.get_financial_dataset(company, periods=periods or None, period_type=period_type)
            selected = periods or sorted(dataset["records"].keys(), reverse=True)[:4]
            base = analyze_periods(company, dataset, selected, period_type)

            task.update({"status": "BUILDING_CONTEXT", "progress": 35, "current_step": "正在构建年报证据上下文"})
            documents = [doc for doc in self.data_service.list_profile_documents(company) if not selected or doc.get("period") in selected]
            for document in documents[:3]:
                self.data_service.materialize_document(document)
            facts = [item for item in self.data_service.knowledge_financial_facts(company, selected) if item.get("quality_status") == "validated"]
            blocks = _balanced_document_blocks(self.data_service, documents[:3], 60)
            fingerprint = json_hash({"company": company["id"], "period_type": period_type, "periods": selected, "facts": facts, "blocks": [{"id": item["block_id"], "text": item.get("text", "")} for item in blocks], "agent": PROMPT_VERSION})
            cached = self.data_service.knowledge.get_completed_model_run("financial_analysis", fingerprint)
            if cached and cached.get("output"):
                result = cached["output"]
                result.setdefault("generation_meta", {})["cache_status"] = "HIT"
            else:
                task.update({"status": "EXTRACTING_FACTS", "progress": 55, "current_step": "正在由 DeepSeek 抽取财务与经营事实"})
                self.data_service.knowledge.start_model_run({"run_id": run_id, "company_id": company["id"], "run_type": "financial_analysis", "input_fingerprint": fingerprint, "model_provider": self.agent.llm_client.provider, "model_name": self.agent.llm_client.model, "prompt_version": PROMPT_VERSION, "status": "RUNNING", "created_at": utc_now()})
                task.update({"status": "ANALYZING_TRENDS", "progress": 72, "current_step": "正在分析趋势、利润质量与现金流"})
                result = self.agent.analyze(company, facts, blocks, period_type, selected)
                task.update({"status": "ASSESSING_RISKS", "progress": 88, "current_step": "正在评估风险关注程度"})
                self.data_service.knowledge.finish_model_run(run_id, "COMPLETED", result)
                result.setdefault("generation_meta", {})["cache_status"] = "MISS"
            analysis_id = "financial_analysis_%s" % uuid.uuid4().hex[:16]
            analysis = _merge(base, result, analysis_id, company, selected)
            self.data_service.knowledge.replace_financial_agent_artifacts(company["id"], analysis_id, result)
            self.analyses[analysis_id] = analysis
            self.store.upsert("financial_agent_analyses", analysis_id, analysis)
            task.update({"status": "COMPLETED", "progress": 100, "current_step": "财报 Agent 分析已生成", "analysis_id": analysis_id, "updated_at": utc_now()})
        except Exception as exc:
            try:
                self.data_service.knowledge.finish_model_run(run_id, "FAILED", error_message=str(exc))
            except Exception:
                pass
            task.update({"status": "FAILED", "progress": task.get("progress", 0), "current_step": "财报 Agent 分析失败", "error": {"code": "FINANCIAL_AGENT_FAILED", "message": _public_error(exc)}, "updated_at": utc_now()})
        finally:
            self.store.upsert("financial_agent_tasks", task["task_id"], task)

    def _task(self, task_id, ticker, market, periods, period_type):
        return {"task_id": task_id, "ticker": ticker, "market": market, "periods": periods, "period_type": period_type, "status": "PENDING", "progress": 5, "current_step": "等待财报 Agent 开始", "company": None, "analysis_id": None, "error": None, "created_at": utc_now(), "updated_at": utc_now()}


def _merge(base, agent_result, analysis_id, company, periods):
    assessments = agent_result.get("risk_assessments", [])
    level_map = {"high": "red", "medium": "yellow", "low": "green", "unknown": "yellow"}
    agent_risks = [{"name": item.get("risk_category") or "风险", "level": level_map.get(item.get("attention_level"), "yellow"), "reason": item.get("assessment_reason") or "证据不足，暂无法形成明确判断。", "uncertainties": item.get("uncertainties", [])} for item in assessments]
    observations = agent_result.get("observations", [])
    observation_claims = [item.get("claim") for item in observations if item.get("claim")]
    business_claims = [item.get("claim") for item in observations if item.get("category") in {"revenue_driver", "business_change"} and item.get("claim")]
    interpretation_points = (
        agent_result.get("earnings_quality", [])
        + agent_result.get("cash_flow_analysis", [])
        + agent_result.get("balance_sheet_analysis", [])
    )
    unavailable_risks = [{
        "name": "Agent 分析状态",
        "level": "yellow",
        "reason": agent_result.get("financial_summary") or "模型服务暂不可用，尚未生成风险等级评估。",
    }]
    return {**base, "analysis_id": analysis_id, "company": company, "selected_periods": periods,
            "agent_analysis": agent_result,
            "summary": agent_result.get("financial_summary") or "披露资料不足，暂无法生成财报 Agent 结论。",
            "trend_insights": agent_result.get("trend_analysis", []),
            "risks": agent_risks if agent_result.get("status") == "completed" else unavailable_risks,
            "business_model": "；".join(business_claims[:2]) or "未从已选披露材料中抽取到可验证的业务驱动信息。",
            "highlights": agent_result.get("trend_analysis", [])[:3],
            "watch_metrics": agent_result.get("uncertainties", [])[:3] or ["后续报告期的收入、利润和经营现金流"],
            "fact_opinion": {
                "facts": observation_claims[:5],
                "inferences": interpretation_points[:4],
                "view": "本页结论由 DeepSeek 基于已验证指标和披露证据生成，不构成投资建议。",
            },
            "score": "--",
            "stance": "neutral",
            "generation_meta": agent_result.get("generation_meta", {}), "disclaimer": base.get("disclaimer")}


def _public_error(exc):
    message = str(exc)
    if "数据质量校验未通过" in message:
        return message
    return "已验证财务事实、披露资料或模型服务暂时不可用，请稍后重试。"


def _balanced_document_blocks(data_service, documents: list[dict], maximum: int) -> list[dict]:
    """Keep multiple selected reports represented in the model context."""
    if not documents:
        return []
    per_document = max(1, maximum // len(documents))
    blocks = []
    for document in documents:
        blocks.extend({**block, "report_period": document.get("period")} for block in data_service.canonical_document_blocks(document)[:per_document])
    return blocks[:maximum]
