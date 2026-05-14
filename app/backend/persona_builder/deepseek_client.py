from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from app.backend.core.config import Settings, get_settings


class DeepSeekClientError(RuntimeError):
    """Raised when DeepSeek cannot produce a usable response."""


@dataclass(frozen=True)
class DeepSeekClient:
    api_key: str
    model: str
    base_url: str
    timeout_seconds: float

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "DeepSeekClient":
        settings = settings or get_settings()
        if not settings.deepseek_api_key:
            raise DeepSeekClientError("DeepSeek API Key 未配置。")
        return cls(
            api_key=settings.deepseek_api_key,
            model=settings.deepseek_model,
            base_url=settings.deepseek_base_url.rstrip("/"),
            timeout_seconds=settings.deepseek_timeout_seconds,
        )

    def complete_json(self, *, system_prompt: str, user_payload: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False),
                },
            ],
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise DeepSeekClientError(f"DeepSeek 请求失败：HTTP {exc.code} {detail}") from exc
        except urllib.error.URLError as exc:
            raise DeepSeekClientError(f"DeepSeek 连接失败：{exc.reason}") from exc
        try:
            data = json.loads(body)
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise DeepSeekClientError("DeepSeek 返回结构不可解析。") from exc
        return _parse_json_content(content)


def _parse_json_content(content: str) -> dict[str, Any]:
    clean = content.strip()
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", clean, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        clean = fence.group(1).strip()
    try:
        data = json.loads(clean)
    except json.JSONDecodeError as exc:
        raise DeepSeekClientError("DeepSeek 返回的 JSON 无法解析。") from exc
    if not isinstance(data, dict):
        raise DeepSeekClientError("DeepSeek 返回的 JSON 顶层不是对象。")
    return data

