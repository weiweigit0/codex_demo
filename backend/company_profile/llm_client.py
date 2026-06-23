from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from typing import Optional

import requests

from backend.config import load_local_env


class ModelProviderClient:
    """OpenAI-compatible structured-output client with provider-specific defaults."""

    def __init__(self):
        load_local_env()
        self.provider = os.getenv("LLM_PROVIDER", "deepseek").strip().lower() or "deepseek"
        if self.provider == "deepseek":
            self.api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
            self.model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash").strip() or "deepseek-v4-flash"
            self.endpoint = os.getenv("DEEPSEEK_CHAT_COMPLETIONS_URL", "https://api.deepseek.com/chat/completions")
        elif self.provider == "openai":
            self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
            self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
            self.endpoint = os.getenv("OPENAI_CHAT_COMPLETIONS_URL", "https://api.openai.com/v1/chat/completions")
        else:
            self.api_key = ""
            self.model = ""
            self.endpoint = ""
        self.transport = (
            os.getenv("LLM_TRANSPORT")
            or os.getenv("%s_TRANSPORT" % self.provider.upper())
            or "requests"
        ).strip().lower()
        self.last_error = ""

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def chat_json(self, system_prompt: str, user_prompt: str, timeout: int = 60) -> Optional[dict]:
        if not self.available:
            self.last_error = "未配置 %s 的 API Key。" % self.provider
            return None
        if self.transport == "curl":
            return self._chat_json_with_curl(system_prompt, user_prompt, timeout)
        try:
            response = requests.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=self._payload(system_prompt, user_prompt),
                timeout=timeout,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return _json_from_text(content)
        except Exception as exc:
            self.last_error = _safe_error_message(str(exc))
            return None

    def _chat_json_with_curl(self, system_prompt: str, user_prompt: str, timeout: int) -> Optional[dict]:
        payload = self._payload(system_prompt, user_prompt)
        proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy") or ""
        config_lines = [
            'url = "%s"' % self.endpoint,
            'request = "POST"',
            'header = "Authorization: Bearer %s"' % self.api_key,
            'header = "Content-Type: application/json"',
            'header = "Accept: application/json"',
            "silent",
            "show-error",
            "fail-with-body",
            "connect-timeout = %d" % min(timeout, 15),
            "max-time = %d" % timeout,
        ]
        if proxy:
            config_lines.append('proxy = "%s"' % proxy)

        config_path = None
        body_path = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as config_file:
                config_file.write("\n".join(config_lines))
                config_path = config_file.name
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as body_file:
                json.dump(payload, body_file, ensure_ascii=False)
                body_path = body_file.name
            os.chmod(config_path, 0o600)
            os.chmod(body_path, 0o600)
            response = subprocess.run(
                ["curl", "--config", config_path, "--data-binary", "@%s" % body_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout + 5,
            )
            if response.returncode != 0:
                self.last_error = _safe_error_message(response.stdout or response.stderr)
                return None
            content = json.loads(response.stdout or "{}")["choices"][0]["message"]["content"]
            return _json_from_text(content)
        except Exception as exc:
            self.last_error = _safe_error_message(str(exc))
            return None
        finally:
            for path in (config_path, body_path):
                if path:
                    try:
                        os.unlink(path)
                    except OSError:
                        pass

    def _payload(self, system_prompt: str, user_prompt: str) -> dict:
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "max_tokens": 8000,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if self.provider == "deepseek":
            payload["response_format"] = {"type": "json_object"}
        return payload


# Backwards-compatible name for callers that have not yet migrated imports.
LLMClient = ModelProviderClient


def _json_from_text(text: str) -> Optional[dict]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        payload = json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return None
        payload = json.loads(match.group(0))
    return payload if isinstance(payload, dict) else None


def _safe_error_message(message: str) -> str:
    """Keep upstream diagnostics useful without retaining credentials or response bodies."""
    message = re.sub(r"Bearer\\s+[^\\s\\\"']+", "Bearer [redacted]", message or "")
    message = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-[redacted]", message)
    return message[:500]
