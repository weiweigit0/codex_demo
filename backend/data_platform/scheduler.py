from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from threading import Event, Thread

from backend.data_platform.service import DataService


class MaintenanceScheduler:
    """Optional lightweight scheduler for quarterly top-company refreshes.

    Disabled by default so a local development restart never creates network jobs.
    Production can enable it with DATA_SCHEDULED_REFRESH=true.
    """

    def __init__(self, data_service: DataService):
        self.data_service = data_service
        self._stop = Event()

    def start_if_enabled(self) -> None:
        if os.getenv("DATA_SCHEDULED_REFRESH", "false").lower() not in {"1", "true", "yes"}:
            return
        Thread(target=self._run, daemon=True, name="data-platform-maintenance").start()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._run_due_quarterly_prewarm()
            self._stop.wait(6 * 60 * 60)

    def _run_due_quarterly_prewarm(self) -> None:
        key = "quarterly_top_company_prewarm"
        snapshot = self.data_service.repository.get_snapshot("maintenance", key, allow_stale=True)
        if snapshot:
            updated = datetime.fromisoformat(snapshot["updated_at"])
            if datetime.now(timezone.utc) - updated < timedelta(days=90):
                return
        jobs = self.data_service.request_prewarm("ALL", ["financial_dataset", "documents"], limit=20)
        self.data_service.repository.save_snapshot(
            "maintenance",
            key,
            {"job_ids": [job["job_id"] for job in jobs], "policy": "top20-quarterly"},
            source_version="maintenance_v1",
        )
