import tempfile
import unittest
from pathlib import Path

from backend.data_platform.service import DataService
from backend.repositories.sqlite_store import SQLiteStore


class FakeSecClient:
    def __init__(self):
        self.resolve_calls = []

    def resolve_company(self, ticker):
        self.resolve_calls.append(ticker)
        return {
            "ticker": "BIDU",
            "name": "Baidu, Inc.",
            "cik": "1329099",
            "market": "US",
            "source": "SEC EDGAR",
        }


class DataServiceIdentityTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.service = DataService(root, SQLiteStore(root))
        self.sec = FakeSecClient()
        self.service.sec_client = self.sec
        self.service.repository.upsert_company({
            "id": "US-BIDU", "ticker": "BIDU", "name": "Baidu, Inc.",
            "market": "US", "cik": None, "source": None,
        })

    def tearDown(self):
        self.directory.cleanup()

    def test_resolve_repairs_cached_us_company_missing_cik(self):
        company = self.service.resolve_company("BIDU", "US")

        self.assertEqual(company["cik"], "1329099")
        self.assertEqual(company["identity_status"], "VERIFIED")
        self.assertEqual(company["identity_source"], "SEC_EDGAR")
        self.assertEqual(self.sec.resolve_calls, ["BIDU"])
        persisted = self.service.repository.get_company("BIDU", "US")
        self.assertEqual(persisted["cik"], "1329099")
        repairs = self.service.repository.list_company_identity_repairs("US-BIDU")
        self.assertEqual(repairs[0]["status"], "SUCCEEDED")
        self.assertEqual(repairs[0]["original"]["cik"], None)

    def test_repair_failure_marks_company_for_review_and_is_audited(self):
        class FailingSecClient:
            def resolve_company(self, _ticker):
                from backend.services.sec_client import SecClientError
                raise SecClientError("SEC unavailable")

        self.service.sec_client = FailingSecClient()
        with self.assertRaisesRegex(Exception, "自动补齐失败"):
            self.service.resolve_company("BIDU", "US")

        company = self.service.repository.get_company("BIDU", "US")
        self.assertEqual(company["identity_status"], "NEEDS_REVIEW")
        repairs = self.service.repository.list_company_identity_repairs("US-BIDU")
        self.assertEqual(repairs[0]["status"], "FAILED")

    def test_search_does_not_return_incomplete_us_cache_record(self):
        results = self.service.search_companies("BIDU", "US")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["cik"], "1329099")
