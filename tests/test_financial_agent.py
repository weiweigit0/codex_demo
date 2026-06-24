import unittest

from backend.financial_agent.agent import FinancialAnalysisAgent
from backend.financial_agent.orchestrator import _balanced_document_blocks, _error_payload
from backend.data_platform.company_identity import CompanyIdentityError


class FakeDeepSeek:
    available = True
    provider = "deepseek"
    model = "deepseek-v4-flash"

    def __init__(self):
        self.calls = 0

    def chat_json(self, _system, _prompt, timeout=60):
        self.calls += 1
        if self.calls == 1:
            return {
                "observations": [{
                    "category": "revenue_driver", "claim": "收入增长来自披露的产品销售。",
                    "period": "2024-FY", "evidence_block_ids": ["doc-1-b-1", "forged-id"],
                }],
                "risk_facts": [{
                    "risk_category": "现金流", "risk_name": "经营现金流波动",
                    "description": "披露提及经营活动现金流波动。", "trend": "unknown",
                    "mitigation_disclosed": [], "evidence_block_ids": ["doc-1-b-2"],
                }],
            }
        if self.calls == 2:
            return {
                "financial_summary": "基于已验证指标和披露材料，收入保持增长。",
                "trend_analysis": ["收入同比增长。"], "earnings_quality": [],
                "cash_flow_analysis": [], "balance_sheet_analysis": [],
                "industry_position": [], "uncertainties": ["未提供完整同业数据。"],
            }
        return {"risk_assessments": [{
            "risk_category": "现金流", "attention_level": "medium",
            "assessment_reason": "披露了现金流波动，需持续关注。",
            "positive_signals": [], "negative_signals": ["存在波动"],
            "uncertainties": [], "evidence_fact_ids": ["risk_fact_0", "invented-risk"],
        }]}


class FinancialAnalysisAgentTest(unittest.TestCase):
    def test_identity_failure_is_not_reported_as_model_failure(self):
        payload = _error_payload(CompanyIdentityError("missing cik", ["cik"]))

        self.assertEqual(payload["code"], "COMPANY_IDENTITY_INCOMPLETE")
        self.assertEqual(payload["source"], "company_identity")

    def test_agent_only_retains_real_evidence_and_fact_ids(self):
        agent = FinancialAnalysisAgent(FakeDeepSeek())
        result = agent.analyze(
            {"name": "测试公司", "ticker": "TEST"},
            [{"metric_key": "revenue", "value": 100.0, "period": "2024-FY"}],
            [
                {"block_id": "doc-1-b-1", "page_number": 1, "text": "产品销售收入增加"},
                {"block_id": "doc-1-b-2", "page_number": 2, "text": "经营活动现金流存在波动"},
            ],
            "annual", ["2024-FY"],
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["observations"][0]["evidence_block_ids"], ["doc-1-b-1"])
        self.assertEqual(result["risk_facts"][0]["fact_id"], "risk_fact_0")
        self.assertEqual(result["risk_assessments"][0]["evidence_fact_ids"], ["risk_fact_0"])

    def test_agent_retries_when_us_filing_produces_english_free_text(self):
        class EnglishFirstResponse:
            available = True
            provider = "deepseek"
            model = "deepseek-v4-flash"

            def __init__(self):
                self.calls = 0
                self.systems = []

            def chat_json(self, system, _prompt, timeout=60):
                self.calls += 1
                self.systems.append(system)
                if self.calls == 1:
                    return {"observations": [{"category": "revenue_driver", "claim": "Revenue grew because of product sales.", "period": "2024-FY", "evidence_block_ids": ["doc-1-b-1"]}], "risk_facts": []}
                if self.calls == 2:
                    return {"observations": [{"category": "revenue_driver", "claim": "产品销售带动收入增长。", "period": "2024-FY", "evidence_block_ids": ["doc-1-b-1"]}], "risk_facts": []}
                if self.calls == 3:
                    return {"financial_summary": "收入表现需要结合披露持续观察。", "trend_analysis": ["已披露产品销售收入变化。"], "earnings_quality": [], "cash_flow_analysis": [], "balance_sheet_analysis": [], "industry_position": [], "uncertainties": []}
                return {"risk_assessments": []}

        client = EnglishFirstResponse()
        result = FinancialAnalysisAgent(client).analyze(
            {"name": "Apple", "ticker": "AAPL"}, [],
            [{"block_id": "doc-1-b-1", "page_number": 1, "text": "Product sales increased."}],
            "annual", ["2024-FY"],
        )

        self.assertEqual(client.calls, 4)
        self.assertEqual(result["observations"][0]["claim"], "产品销售带动收入增长。")
        self.assertIn("上一版存在英文自由文本", client.systems[1])

    def test_multi_period_context_is_balanced_across_documents(self):
        class FakeDataService:
            def canonical_document_blocks(self, document):
                return document["blocks"]

        documents = [
            {"id": "2024", "blocks": [{"block_id": "2024-%d" % index} for index in range(30)]},
            {"id": "2023", "blocks": [{"block_id": "2023-%d" % index} for index in range(30)]},
            {"id": "2022", "blocks": [{"block_id": "2022-%d" % index} for index in range(30)]},
        ]
        blocks = _balanced_document_blocks(FakeDataService(), documents, 60)

        self.assertEqual(len(blocks), 60)
        self.assertEqual(sum(item["block_id"].startswith("2024-") for item in blocks), 20)
        self.assertEqual(sum(item["block_id"].startswith("2023-") for item in blocks), 20)
        self.assertEqual(sum(item["block_id"].startswith("2022-") for item in blocks), 20)


if __name__ == "__main__":
    unittest.main()
