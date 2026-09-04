"""MiniMax-M3 OpenAI 兼容客户端。"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import requests

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResult:
    text: str
    reasoning: str
    raw: dict
    model: str
    duration_ms: int


class MiniMaxClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.minimax.io/v1",
        model: str = "MiniMax-M3",
        thinking_level: int = 2,
        timeout: int = 180,
    ):
        if not api_key:
            raise LLMError("MINIMAX_API_KEY 未配置,无法调用 LLM。")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.thinking_level = thinking_level
        self.timeout = timeout

    def _build_body(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.4,
        max_tokens: int = 2048,
        use_thinking: bool = True,
        response_format_json: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if use_thinking and self.thinking_level > 0:
            body["reasoning_split"] = True
            body["thinking"] = {"type": "adaptive" if self.thinking_level >= 2 else "enabled"}
        if response_format_json:
            body["response_format"] = {"type": "json_object"}
        return body

    def chat(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.4,
        max_tokens: int = 2048,
        use_thinking: bool = True,
        response_format_json: bool = False,
    ) -> LLMResult:
        url = f"{self.base_url}/chat/completions"
        body = self._build_body(
            system,
            user,
            temperature=temperature,
            max_tokens=max_tokens,
            use_thinking=use_thinking,
            response_format_json=response_format_json,
        )
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        started = time.time()
        try:
            r = requests.post(url, headers=headers, json=body, timeout=self.timeout)
        except requests.RequestException as exc:
            raise LLMError(f"调用 LLM 网络失败:{exc}") from exc
        duration_ms = int((time.time() - started) * 1000)
        if r.status_code >= 400:
            raise LLMError(f"LLM {r.status_code}: {r.text[:800]}")
        try:
            data = r.json()
        except ValueError as exc:
            raise LLMError(f"LLM 响应非 JSON: {r.text[:500]}") from exc

        choices = data.get("choices") or []
        if not choices:
            raise LLMError(f"LLM 响应无 choices: {data}")
        msg = choices[0].get("message") or {}
        text = msg.get("content") or ""
        reasoning = ""
        if isinstance(msg.get("reasoning_details"), list):
            reasoning = "\n".join(
                str(x.get("text", "")) for x in msg["reasoning_details"] if isinstance(x, dict)
            )
        elif msg.get("reasoning"):
            reasoning = str(msg["reasoning"])
        return LLMResult(
            text=text,
            reasoning=reasoning,
            raw=data,
            model=data.get("model", self.model),
            duration_ms=duration_ms,
        )
