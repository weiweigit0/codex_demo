from __future__ import annotations

import uuid
from threading import RLock, Thread

from backend.data_platform.repository import json_hash, utc_now
from backend.three_minute_summary.video_agent import VIDEO_PROMPT_VERSION, VideoScriptAgent


class VideoScriptOrchestrator:
    def __init__(self, summary_orchestrator):
        self.summary_orchestrator = summary_orchestrator
        self.repository = summary_orchestrator.repository
        self.agent = VideoScriptAgent()
        self.tasks = {}
        self._lock = RLock()

    def create_script(self, summary_id):
        task = {"task_id": _id("video_task"), "status": "PENDING", "progress": 5, "current_step": "等待短视频脚本 Agent", "script_id": None, "error": None, "created_at": utc_now(), "updated_at": utc_now()}
        with self._lock:
            self.tasks[task["task_id"]] = task
        Thread(target=self._run, args=(task, summary_id), daemon=True).start()
        return task

    def get_task(self, task_id):
        with self._lock:
            task = self.tasks.get(task_id)
        if not task:
            raise KeyError("视频脚本任务不存在")
        return task

    def get_script(self, script_id):
        script = self.repository.get_video(script_id)
        if not script:
            raise KeyError("视频脚本不存在")
        return script

    def _run(self, task, summary_id):
        try:
            _update(task, "READING_SUMMARY", 25, "正在读取已验证总结")
            summary = self.summary_orchestrator.get_summary(summary_id)
            if summary.get("status") != "completed":
                raise ValueError("当前总结不可用于生成短视频脚本。")
            fingerprint = json_hash({"summary": summary_id, "content": {key: summary.get(key) for key in ("total_score", "one_line_summary", "three_minute_summary", "score_cards", "key_points", "risks")}, "agent": VIDEO_PROMPT_VERSION})
            cached = self.repository.get_video_by_fingerprint(fingerprint)
            if cached:
                cached.setdefault("generation_meta", {})["cache_status"] = "HIT"
                self.repository.save_video(cached, fingerprint)
                _update(task, "COMPLETED", 100, "已命中短视频脚本缓存", script_id=cached["script_id"])
                return
            _update(task, "WRITING_SCRIPT", 65, "正在生成口播与分镜")
            result = self.agent.generate(summary)
            script = {"script_id": _id("video_script"), "summary_id": summary_id, "company": summary["company"], "period": summary["period"], **result, "disclaimer": summary.get("disclaimer"), "created_at": utc_now()}
            script.setdefault("generation_meta", {})["cache_status"] = "MISS"
            self.repository.save_video(script, fingerprint, "COMPLETED" if result["status"] == "completed" else "UNAVAILABLE")
            _update(task, "COMPLETED", 100, "短视频脚本已生成", script_id=script["script_id"])
        except Exception as exc:
            _update(task, "FAILED", task.get("progress", 0), "短视频脚本生成失败", error={"code": "VIDEO_SCRIPT_FAILED", "message": str(exc)[:300]})


def _id(prefix): return "%s_%s" % (prefix, uuid.uuid4().hex[:16])
def _update(task, status, progress, step, **extra): task.update({"status": status, "progress": progress, "current_step": step, "updated_at": utc_now(), **extra})
