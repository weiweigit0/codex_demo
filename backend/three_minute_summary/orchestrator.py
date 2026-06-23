from __future__ import annotations

import uuid
from threading import RLock, Thread

from backend.data_platform.repository import utc_now
from backend.three_minute_summary.agent import SUMMARY_PROMPT_VERSION, ThreeMinuteSummaryAgent
from backend.three_minute_summary.knowledge_reader import SummaryKnowledgeReader
from backend.three_minute_summary.repository import ThreeMinuteSummaryRepository


class ThreeMinuteSummaryOrchestrator:
    def __init__(self, data_service, sqlite_store):
        self.reader = SummaryKnowledgeReader(data_service)
        self.agent = ThreeMinuteSummaryAgent()
        self.repository = ThreeMinuteSummaryRepository(sqlite_store)
        self.tasks = {}
        self._lock = RLock()

    def create_summary(self, ticker, market, period_type, period, allow_web_enrichment=False):
        task_id = _id("summary_task")
        task = {"task_id": task_id, "status": "PENDING", "progress": 5, "current_step": "等待三分钟总结 Agent", "summary_id": None, "error": None, "created_at": utc_now(), "updated_at": utc_now()}
        with self._lock:
            self.tasks[task_id] = task
        Thread(target=self._run, args=(task, ticker, market, period_type, period, allow_web_enrichment), daemon=True).start()
        return task

    def get_task(self, task_id):
        with self._lock:
            task = self.tasks.get(task_id)
        if not task:
            raise KeyError("总结任务不存在")
        return task

    def get_summary(self, summary_id):
        result = self.repository.get_summary(summary_id)
        if not result:
            raise KeyError("总结结果不存在")
        return result

    def get_public_summary(self, summary_id):
        summary = self.get_summary(summary_id)
        evidence = [{"block_id": item.get("block_id"), "page_number": item.get("page_number"), "section_title": item.get("section_title")} for item in summary.get("context", {}).get("filing_evidence_blocks", [])]
        result = {key: value for key, value in summary.items() if key != "context"}
        result["evidence_index"] = evidence
        result["external_sources"] = summary.get("context", {}).get("external_sources", [])
        return result

    def answer_question(self, summary_id, question):
        summary = self.get_summary(summary_id)
        context = summary.get("context", {})
        blocks = context.get("filing_evidence_blocks", [])
        result = self.agent.answer(_public_summary(summary), question, blocks)
        result["question_id"] = _id("summary_question")
        self.repository.save_question(result["question_id"], summary_id, question, result)
        return result

    def _run(self, task, ticker, market, period_type, period, allow_web_enrichment):
        try:
            _update(task, "BUILDING_CONTEXT", 20, "正在读取统一知识与报告证据")
            context = self.reader.build_context(ticker, market, period_type, period, allow_web_enrichment)
            if context.get("external_sources"):
                self.repository.save_search_sources(context["company"]["id"], context["external_sources"])
            fingerprint = "%s:%s" % (SUMMARY_PROMPT_VERSION, context["fingerprint"])
            cached = self.repository.get_summary_by_fingerprint(fingerprint)
            if cached:
                cached.setdefault("generation_meta", {})["cache_status"] = "HIT"
                self.repository.save_summary(cached, fingerprint)
                _update(task, "COMPLETED", 100, "已命中三分钟总结缓存", summary_id=cached["summary_id"])
                return
            _update(task, "GENERATING_SCORE", 55, "正在生成经营理解评分")
            result = self.agent.generate(context)
            summary_id = _id("three_minute_summary")
            summary = {"summary_id": summary_id, "company": context["company"], "period": context["period"], "period_type": context["period_type"], "status": result["status"], **result, "context": _stored_context(context), "disclaimer": "本内容仅用于财报信息理解和研究辅助，不构成任何投资建议。", "created_at": utc_now()}
            summary.setdefault("generation_meta", {})["cache_status"] = "MISS"
            self.repository.save_summary(summary, fingerprint, "COMPLETED" if result["status"] == "completed" else "UNAVAILABLE")
            _update(task, "COMPLETED", 100, "三分钟财报总结已生成", summary_id=summary_id)
        except Exception as exc:
            _update(task, "FAILED", task.get("progress", 0), "三分钟总结生成失败", error={"code": "SUMMARY_FAILED", "message": _public_error(exc)})


def _stored_context(context):
    return {key: context[key] for key in ("filing_evidence_blocks", "coverage", "external_sources")}


def _public_summary(summary):
    return {key: summary.get(key) for key in ("company", "period", "total_score", "one_line_summary", "three_minute_summary", "key_points", "risks", "watch_items", "uncertainties")}


def _update(task, status, progress, step, **extra):
    with_task = {"status": status, "progress": progress, "current_step": step, "updated_at": utc_now(), **extra}
    task.update(with_task)


def _id(prefix):
    return "%s_%s" % (prefix, uuid.uuid4().hex[:16])


def _public_error(exc):
    text = str(exc)
    if "数据质量校验未通过" in text or "没有可用于" in text:
        return text
    return "统一知识、披露文件或模型服务暂时不可用，请稍后重试。"
