import unittest

from backend.data_platform.company_identity import CompanyIdentityError
from backend.services.sec_client import SecClient, SecClientError


class CompanyIdentityBoundaryTest(unittest.TestCase):
    def test_sec_client_rejects_empty_cik_with_business_error(self):
        with self.assertRaises(SecClientError) as error:
            SecClient().fetch_companyfacts(None)

        self.assertIn("缺少可用的 SEC CIK", str(error.exception))

    def test_identity_error_has_stable_code(self):
        error = CompanyIdentityError("missing", ["cik"])

        self.assertEqual(error.code, "COMPANY_IDENTITY_INCOMPLETE")
        self.assertEqual(error.missing_fields, ["cik"])
