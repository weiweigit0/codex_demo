from pathlib import Path

from backend.data_sources.ashare_source import AShareSource
from backend.data_sources.sec_source import SecClient
from backend.repositories.json_store import JsonStore
from backend.repositories.sqlite_store import SQLiteStore
from backend.services.auth_service import AuthService
from backend.services.company_service import CompanyService
from backend.services.industry_service import IndustryService
from backend.services.report_service import ReportService
from backend.services.watchlist_service import WatchlistService


class ServiceContainer:
    def __init__(self, storage_dir: Path):
        self.store = JsonStore(storage_dir)
        self.sqlite_store = SQLiteStore(storage_dir)
        self.sec_client = SecClient()
        self.ashare_source = AShareSource()
        self.auth_service = AuthService(self.sqlite_store)
        self.company_service = CompanyService(self.sec_client, self.ashare_source)
        self.report_service = ReportService(self.store, self.sec_client, self.ashare_source)
        self.industry_service = IndustryService(self.company_service, self.report_service)
        self.watchlist_service = WatchlistService(self.store)
