from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import requests


class ProviderError(RuntimeError):
    pass


@dataclass
class TtsAsset:
    path: Path
    mime_type: str


class VolcTtsProvider:
    """Server-side ByteDance/Volcengine HTTP TTS adapter.

    Credentials remain only in the independent media service environment.
    The provider returns source audio; subtitles stay deterministic from VideoBrief.
    """

    def __init__(self):
        self.app_id = os.getenv("VOLC_TTS_APP_ID", "").strip()
        self.token = os.getenv("VOLC_TTS_TOKEN", "").strip()
        self.cluster = os.getenv("VOLC_TTS_CLUSTER", "volcano_tts").strip()
        self.voice_type = os.getenv("VOLC_TTS_VOICE_TYPE", "").strip()
        self.endpoint = os.getenv("VOLC_TTS_URL", "https://openspeech.bytedance.com/api/v1/tts").strip()
        self.timeout = int(os.getenv("MEDIA_PROVIDER_TIMEOUT_SECONDS", "90"))
        self.session = _session()

    def configured(self) -> bool:
        return bool(self.app_id and self.token and self.voice_type)

    def synthesize(self, text: str, output_path: Path, request_id: str) -> TtsAsset:
        if not self.configured():
            raise ProviderError("未配置 VOLC_TTS_APP_ID、VOLC_TTS_TOKEN 或 VOLC_TTS_VOICE_TYPE。")
        payload = {
            "app": {"appid": self.app_id, "token": self.token, "cluster": self.cluster},
            "user": {"uid": "media-%s" % request_id[-20:]},
            "audio": {"voice_type": self.voice_type, "encoding": "mp3", "speed_ratio": 1.0, "volume_ratio": 1.0, "pitch_ratio": 1.0},
            "request": {"reqid": "tts_%s" % uuid.uuid4().hex, "text": text, "text_type": "plain", "operation": "query", "with_timestamp": 1},
        }
        response = self.session.post(self.endpoint, headers={"Authorization": "Bearer;%s" % self.token, "Content-Type": "application/json"}, json=payload, timeout=self.timeout)
        _ensure_http(response, "豆包 TTS")
        body = response.json()
        if body.get("code") not in (0, 3000, 20000000):
            raise ProviderError("豆包 TTS 返回失败：%s" % str(body.get("message") or body.get("code")))
        encoded = body.get("data")
        if not isinstance(encoded, str) or not encoded:
            raise ProviderError("豆包 TTS 未返回音频数据。")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            output_path.write_bytes(base64.b64decode(encoded))
        except Exception as exc:
            raise ProviderError("豆包 TTS 音频解码失败：%s" % exc) from exc
        return TtsAsset(output_path, "audio/mpeg")


class VolcSignedClient:
    """Minimal Volcengine HMAC-SHA256 signer for the visual API."""

    def __init__(self):
        self.access_key = os.getenv("JIMENG_ACCESS_KEY", "").strip()
        self.secret_key = os.getenv("JIMENG_SECRET_KEY", "").strip()
        self.endpoint = os.getenv("JIMENG_ENDPOINT", "https://visual.volcengineapi.com").rstrip("/")
        self.region = os.getenv("JIMENG_REGION", "cn-north-1")
        self.service = os.getenv("JIMENG_SERVICE", "cv")
        self.timeout = int(os.getenv("MEDIA_PROVIDER_TIMEOUT_SECONDS", "90"))
        self.session = _session()

    def configured(self) -> bool:
        return bool(self.access_key and self.secret_key)

    def post(self, action: str, payload: dict) -> dict:
        if not self.configured():
            raise ProviderError("未配置 JIMENG_ACCESS_KEY 或 JIMENG_SECRET_KEY。")
        query = {"Action": action, "Version": "2022-08-31"}
        encoded_body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = self._headers(query, encoded_body)
        response = self.session.post(self.endpoint, params=query, data=encoded_body, headers=headers, timeout=self.timeout)
        _ensure_http(response, "即梦视频")
        try:
            return response.json()
        except Exception as exc:
            raise ProviderError("即梦视频返回非 JSON 内容。") from exc

    def _headers(self, query: dict, body: bytes) -> dict:
        now = datetime.now(timezone.utc)
        date = now.strftime("%Y%m%d")
        timestamp = now.strftime("%Y%m%dT%H%M%SZ")
        host = self.endpoint.split("://", 1)[-1].split("/", 1)[0]
        canonical_query = "&".join("%s=%s" % (quote(key, safe="-_.~"), quote(str(value), safe="-_.~")) for key, value in sorted(query.items()))
        body_hash = hashlib.sha256(body).hexdigest()
        canonical_headers = "host:%s\nx-content-sha256:%s\nx-date:%s\n" % (host, body_hash, timestamp)
        signed_headers = "host;x-content-sha256;x-date"
        canonical_request = "POST\n/\n%s\n%s\n%s\n%s" % (canonical_query, canonical_headers, signed_headers, body_hash)
        scope = "%s/%s/%s/request" % (date, self.region, self.service)
        string_to_sign = "HMAC-SHA256\n%s\n%s\n%s" % (timestamp, scope, hashlib.sha256(canonical_request.encode("utf-8")).hexdigest())
        signing_key = _hmac(_hmac(_hmac(_hmac(self.secret_key.encode("utf-8"), date), self.region), self.service), "request")
        signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        authorization = "HMAC-SHA256 Credential=%s/%s, SignedHeaders=%s, Signature=%s" % (self.access_key, scope, signed_headers, signature)
        return {"Content-Type": "application/json", "Host": host, "X-Date": timestamp, "X-Content-Sha256": body_hash, "Authorization": authorization}


class JimengVideoProvider:
    """Official asynchronous text-to-video flow: submit, poll, then download."""

    def __init__(self, client: Optional[VolcSignedClient] = None):
        self.client = client or VolcSignedClient()
        self.req_key = os.getenv("JIMENG_TEXT_TO_VIDEO_REQ_KEY", "jimeng_t2v_v30")
        self.poll_interval = float(os.getenv("JIMENG_POLL_INTERVAL_SECONDS", "4"))
        self.poll_timeout = int(os.getenv("JIMENG_POLL_TIMEOUT_SECONDS", "900"))
        self.session = _session()

    def configured(self) -> bool:
        return self.client.configured()

    def generate(self, prompt: str, duration_seconds: int, ratio: str, output_path: Path) -> Path:
        frames = 241 if duration_seconds >= 10 else 121
        submitted = self.client.post("CVSync2AsyncSubmitTask", {"req_key": self.req_key, "prompt": prompt, "seed": -1, "frames": frames, "aspect_ratio": ratio})
        task_id = (submitted.get("data") or {}).get("task_id")
        if submitted.get("code") != 10000 or not task_id:
            raise ProviderError("即梦任务提交失败：%s" % str(submitted.get("message") or submitted.get("code")))
        deadline = time.monotonic() + self.poll_timeout
        while time.monotonic() < deadline:
            result = self.client.post("CVSync2AsyncGetResult", {"req_key": self.req_key, "task_id": task_id})
            data = result.get("data") or {}
            status = data.get("status")
            if result.get("code") == 10000 and status == "done" and data.get("video_url"):
                response = self.session.get(data["video_url"], timeout=getattr(self.client, "timeout", 90))
                _ensure_http(response, "即梦视频下载")
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(response.content)
                return output_path
            if status in {"failed", "expired", "not_found"} or result.get("code") not in (10000, None):
                raise ProviderError("即梦任务失败：%s" % str(result.get("message") or status or result.get("code")))
            time.sleep(self.poll_interval)
        raise ProviderError("即梦任务轮询超时。")


def _hmac(key: bytes, value: str) -> bytes:
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()


def _session() -> requests.Session:
    session = requests.Session()
    session.trust_env = os.getenv("MEDIA_PROVIDER_USE_ENV_PROXY", "false").lower() in {"1", "true", "yes"}
    return session


def _ensure_http(response: requests.Response, provider: str) -> None:
    if response.ok:
        return
    message = (response.text or "")[:400]
    raise ProviderError("%s HTTP %s：%s" % (provider, response.status_code, message))
