import unittest

from backend.three_minute_summary.agent import ThreeMinuteSummaryAgent
from backend.three_minute_summary.agent import _safe_text
from backend.three_minute_summary.video_agent import VideoScriptAgent


class FakeModel:
    available = True
    provider = "deepseek"
    model = "deepseek-v4-flash"

    def __init__(self, payload):
        self.payload = payload

    def chat_json(self, *_args, **_kwargs):
        return self.payload


class ThreeMinuteSummaryTests(unittest.TestCase):
    def test_summary_discards_uncited_score_cards(self):
        payload = {
            "one_line_summary": "测试总结", "three_minute_summary": "这是一个有证据的通俗总结。",
            "score_cards": [
                {"dimension": "业务清晰度与竞争位置", "score": 15, "reason": "有证据", "confidence": "high", "evidence_block_ids": ["b1"]},
                {"dimension": "增长与盈利趋势", "score": 15, "reason": "有证据", "confidence": "high", "evidence_block_ids": ["b1"]},
                {"dimension": "现金流与利润质量", "score": 15, "reason": "有证据", "confidence": "high", "evidence_block_ids": ["b1"]},
                {"dimension": "资产负债与经营韧性", "score": 10, "reason": "有证据", "confidence": "high", "evidence_block_ids": ["b1"]},
                {"dimension": "风险与不确定性", "score": 15, "reason": "伪造引用", "confidence": "high", "evidence_block_ids": ["forged"]},
            ],
        }
        context = {"company": {"name": "测试公司", "ticker": "TEST"}, "period": "2025-FY", "validated_financial_facts": [], "filing_evidence_blocks": [{"block_id": "b1", "text": "披露依据"}], "company_profile_facts": [], "financial_agent_artifacts": [], "external_sources": []}
        result = ThreeMinuteSummaryAgent(FakeModel(payload)).generate(context)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["score_cards"]), 4)
        self.assertTrue(all(card["evidence_block_ids"] == ["b1"] for card in result["score_cards"]))

    def test_video_agent_downgrades_overconfident_narration(self):
        payload = {"segments": [{"title": "现金流", "duration_seconds": 20, "narration": "这不影响主营业务，一定会恢复。", "visual_direction": "趋势图", "on_screen_metrics": [], "evidence_refs": ["b1"]} for _ in range(4)]}
        summary = {"company": {"name": "测试公司"}, "period": "2025-FY", "score_cards": [{"evidence_block_ids": ["b1"]}], "key_points": [], "risks": []}
        result = VideoScriptAgent(FakeModel(payload)).generate(summary)

        self.assertEqual(result["status"], "completed")
        self.assertNotIn("不影响主营业务", result["segments"][0]["narration"])
        self.assertNotIn("一定会", result["segments"][0]["narration"])

    def test_summary_sanitizes_common_knowledge_overclaim(self):
        text = _safe_text("根据行业常识判断大概率增长，实际风险较低。")

        self.assertNotIn("行业常识", text)
        self.assertNotIn("实际风险较低", text)


if __name__ == "__main__":
    unittest.main()
