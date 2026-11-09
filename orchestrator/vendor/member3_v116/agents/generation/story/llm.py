"""LLM 客户端：OpenAI 兼容 /chat/completions，JSON 输出。

没有配 LLM_BASE_URL / LLM_API_KEY 时不会走到这里——builder 直接用模板（mock）。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from ..config import Settings
from ..errors import AppError, ErrorCode, StoryError


class LLMClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.llm_base_url.strip() and self.settings.llm_model.strip())

    def chat_json(self, system: str, user: str, *, timeout: float | None = None) -> dict:
        """调用一次（失败按 §1.13 重试），返回解析后的 JSON 对象。"""
        timeout = timeout or self.settings.story_timeout_sec
        attempts = 1 + max(0, self.settings.max_retry)
        last_error: AppError | None = None

        for attempt in range(1, attempts + 1):
            try:
                raw = self._request(system, user, timeout)
                return self._parse(raw)
            except AppError as exc:
                last_error = exc
                if not exc.retryable or attempt == attempts:
                    raise
                time.sleep(self.settings.retry_backoff_sec)

        raise last_error or StoryError("LLM 调用失败")

    def _request(self, system: str, user: str, timeout: float) -> str:
        base = self.settings.llm_base_url.rstrip("/")
        url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
        payload = {
            "model": self.settings.llm_model,
            "temperature": 0.7,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        }
        headers = {"Content-Type": "application/json"}
        if self.settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self.settings.llm_api_key}"

        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:400].decode("utf-8", "replace")
            raise StoryError(f"LLM 返回 HTTP {exc.code}", detail=detail) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise StoryError("LLM 连接失败或超时", code=ErrorCode.TIMEOUT, detail=str(exc)) from exc

        try:
            data = json.loads(body)
            return data["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise StoryError("LLM 响应结构不符合 OpenAI 兼容格式", detail=body[:400]) from exc

    @staticmethod
    def _parse(content: str) -> dict:
        text = (content or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise StoryError("LLM 输出不是合法 JSON", detail=text[:400]) from exc
        if not isinstance(data, dict) or not isinstance(data.get("segments"), list):
            raise StoryError("LLM 输出缺少 segments 数组", detail=text[:400])
        return data
