import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from backend.media_production.orchestrator import MediaProductionOrchestrator
from backend.media_production.security import sign_payload, verify_payload
from backend.media_production.worker import MediaProductionWorker


class MediaProductionTest(unittest.TestCase):
    def setUp(self):
        self.previous_mode = os.environ.get("MEDIA_RENDER_MODE")
        os.environ["MEDIA_RENDER_MODE"] = "demo"
        self.root = tempfile.TemporaryDirectory()
        self.service = MediaProductionOrchestrator(__import__("pathlib").Path(self.root.name))
        key = Ed25519PrivateKey.generate()
        self.private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode("utf-8")
        self.public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode("utf-8")

    def tearDown(self):
        if self.previous_mode is None:
            os.environ.pop("MEDIA_RENDER_MODE", None)
        else:
            os.environ["MEDIA_RENDER_MODE"] = self.previous_mode
        self.root.cleanup()

    def test_request_waits_for_admin_then_creates_demo_delivery(self):
        brief = self._brief()
        brief["signature"] = sign_payload({key: value for key, value in brief.items() if key != "signature"}, self.private)
        self.assertTrue(verify_payload({key: value for key, value in brief.items() if key != "signature"}, brief["signature"], self.public))
        self.service.import_brief(brief)
        request = self.service.create_request(brief["brief_id"], "vertical_720p")
        pending = self.service.get_request(request["request_id"], request["access_token"])
        self.assertEqual(pending["status"], "PENDING_REVIEW")
        self.assertEqual(pending["assets"], [])
        self.service.review(request["request_id"], "approve", "演示批准", "admin")
        queued = self.service.get_request(request["request_id"], request["access_token"])
        self.assertEqual(queued["status"], "QUEUED")
        MediaProductionWorker(__import__("pathlib").Path(self.root.name)).process(request["request_id"])
        final = self.service.get_request(request["request_id"], request["access_token"])
        self.assertEqual(final["status"], "DEMO_DELIVERED")
        self.assertEqual({item["asset_type"] for item in final["assets"]}, {"production_manifest", "subtitles"})
        with self.assertRaises(PermissionError):
            self.service.get_request(request["request_id"], "forged-token")

    def test_same_content_for_same_requester_is_not_approved_twice(self):
        first = self._brief()
        first["signature"] = sign_payload({key: value for key, value in first.items() if key != "signature"}, self.private)
        self.service.import_brief(first)
        initial = self.service.create_request(first["brief_id"], "vertical_720p")
        second = self._brief()
        second.update({"brief_id": "brief_second", "nonce": "nonce-second"})
        second["signature"] = sign_payload({key: value for key, value in second.items() if key != "signature"}, self.private)
        self.service.import_brief(second)
        duplicate = self.service.create_request(second["brief_id"], "vertical_720p")
        self.assertTrue(duplicate["reused"])
        self.assertEqual(duplicate["request_id"], initial["request_id"])

    def test_signature_changes_when_payload_is_tampered(self):
        brief = self._brief()
        signature = sign_payload({key: value for key, value in brief.items() if key != "signature"}, self.private)
        brief["segments"][0]["narration"] = "被篡改的口播。"
        self.assertFalse(verify_payload({key: value for key, value in brief.items() if key != "signature"}, signature, self.public))

    def test_production_mode_without_providers_fails_without_assets(self):
        os.environ["MEDIA_RENDER_MODE"] = "production"
        service = MediaProductionOrchestrator(__import__("pathlib").Path(self.root.name))
        brief = self._brief()
        brief["signature"] = sign_payload({key: value for key, value in brief.items() if key != "signature"}, self.private)
        service.import_brief(brief)
        request = service.create_request(brief["brief_id"], "vertical_720p")
        service.review(request["request_id"], "approve", "生产模式验收", "admin")
        MediaProductionWorker(__import__("pathlib").Path(self.root.name)).process(request["request_id"])
        result = service.get_request(request["request_id"], request["access_token"])
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["assets"], [])

    def _brief(self):
        now = datetime.now(timezone.utc)
        segments = []
        for index in range(4):
            segments.append({"segment_id": "seg_%02d" % (index + 1), "title": "片段", "target_duration_seconds": 12, "narration": "这是经过验证的中文口播内容。", "visual_direction": "抽象数据背景", "display_facts": [], "evidence_refs": ["block_%d" % index]})
        return {"schema_version": "video_brief_v1", "brief_id": "brief_test", "issued_at": now.isoformat(), "expires_at": (now + timedelta(minutes=30)).isoformat(), "nonce": "nonce-test", "content_hash": "hash", "requester_reference": "opaque-user", "source": {"summary_id": "summary_test", "script_id": "script_test", "script_version": "v1", "company_display_name": "测试公司", "period_display_name": "2025-FY"}, "segments": segments, "content_rules": {"language": "zh-CN", "no_new_facts": True, "no_investment_advice": True}, "key_id": "test", "signature": ""}
