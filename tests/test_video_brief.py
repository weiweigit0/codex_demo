import os
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from backend.media_production.security import verify_payload
from backend.three_minute_summary.video_brief import export_video_brief


class VideoBriefExportTest(unittest.TestCase):
    def setUp(self):
        self.saved = {key: os.environ.get(key) for key in ("VIDEO_BRIEF_PRIVATE_KEY", "VIDEO_BRIEF_SUBJECT_SALT")}
        key = Ed25519PrivateKey.generate()
        self.public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode("utf-8")
        os.environ["VIDEO_BRIEF_PRIVATE_KEY"] = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode("utf-8")
        os.environ["VIDEO_BRIEF_SUBJECT_SALT"] = "test-subject-salt"

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_export_is_signed_and_does_not_invent_metric_values(self):
        script = {
            "script_id": "script_1", "summary_id": "summary_1", "period": "2025-FY",
            "company": {"name": "测试公司"}, "generation_meta": {"agent_version": "video_v4"},
            "segments": [
                {"title": "片段", "duration_seconds": 20, "narration": "已验证的中文口播。", "visual_direction": "数据卡片", "on_screen_metrics": ["营业收入"], "evidence_refs": ["block_%d" % index]}
                for index in range(4)
            ],
            "status": "completed",
        }
        brief = export_video_brief(script, {"id": 8})
        unsigned = {key: value for key, value in brief.items() if key != "signature"}
        self.assertTrue(verify_payload(unsigned, brief["signature"], self.public))
        self.assertIsNone(brief["segments"][0]["display_facts"][0]["display_value"])
        self.assertEqual(brief["content_rules"]["language"], "zh-CN")
