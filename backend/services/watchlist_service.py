from __future__ import annotations

from datetime import datetime

from backend.repositories.json_store import JsonStore


class WatchlistService:
    def __init__(self, store: JsonStore):
        self.store = store

    def list_watchlist(self):
        return self.store.list("watchlist")

    def add_company(self, company: dict):
        item = {
            "id": company["id"],
            "company": company,
            "created_at": datetime.utcnow().isoformat(),
        }
        return self.store.upsert("watchlist", item["id"], item)

    def remove_company(self, company_id: str):
        return self.store.delete("watchlist", company_id)

    def list_alerts(self):
        return self.store.list("alerts")

    def add_alert(self, alert: dict):
        alert_id = f"{alert['company_id']}-{alert['metric']}-{datetime.utcnow().timestamp()}"
        item = {**alert, "id": alert_id, "created_at": datetime.utcnow().isoformat()}
        return self.store.upsert("alerts", alert_id, item)
