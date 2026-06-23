import os
import tempfile
import unittest
from pathlib import Path

from backend.media_production.providers import JimengVideoProvider, VolcSignedClient


class FakeClient:
    def __init__(self):
        self.calls = 0

    def configured(self):
        return True

    def post(self, action, payload):
        self.calls += 1
        if action == "CVSync2AsyncSubmitTask":
            self.submit_payload = payload
            return {"code": 10000, "data": {"task_id": "task-1"}}
        return {"code": 10000, "data": {"status": "done", "video_url": "https://example.invalid/video.mp4"}}


class FakeResponse:
    ok = True
    content = b"fake-mp4-bytes"
    status_code = 200
    text = ""


class FakeSession:
    def get(self, _url, timeout=0):
        return FakeResponse()


class MediaProviderTest(unittest.TestCase):
    def setUp(self):
        self.saved = {key: os.environ.get(key) for key in ("JIMENG_ACCESS_KEY", "JIMENG_SECRET_KEY", "JIMENG_POLL_INTERVAL_SECONDS")}

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_jimeng_signed_client_builds_hmac_authorization(self):
        os.environ["JIMENG_ACCESS_KEY"] = "ak-test"
        os.environ["JIMENG_SECRET_KEY"] = "sk-test"
        headers = VolcSignedClient()._headers({"Action": "CVSync2AsyncSubmitTask", "Version": "2022-08-31"}, b"{}")
        self.assertIn("HMAC-SHA256 Credential=ak-test/", headers["Authorization"])
        self.assertEqual(headers["X-Content-Sha256"], "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a")

    def test_jimeng_provider_submits_polls_and_downloads_clip(self):
        os.environ["JIMENG_POLL_INTERVAL_SECONDS"] = "0"
        provider = JimengVideoProvider(FakeClient())
        provider.session = FakeSession()
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "clip.mp4"
            result = provider.generate("无文字的财经背景", 5, "9:16", target)
            self.assertEqual(result.read_bytes(), b"fake-mp4-bytes")
            self.assertEqual(provider.client.submit_payload["frames"], 121)
            self.assertEqual(provider.client.submit_payload["aspect_ratio"], "9:16")
