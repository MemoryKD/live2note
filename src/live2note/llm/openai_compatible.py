"""OpenAI-compatible API provider."""

from __future__ import annotations

from typing import Any

import httpx

from live2note.llm.base import BaseLLMProvider, LLMResult
from live2note.logger import get_logger

log = get_logger("llm.openai")

_DEFAULT_TIMEOUT = 120


class OpenAICompatibleProvider(BaseLLMProvider):
    """Calls an OpenAI-compatible chat completions API.

    Supports OpenAI, OpenRouter, DeepSeek, MiMo, and any OpenAI-format endpoint.
    """

    def __init__(
        self,
        api_base: str = "https://api.openai.com/v1",
        api_key: str = "",
        model: str = "gpt-4o",
        temperature: float = 0.3,
        max_tokens: int = 4096,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> None:
        self._api_base = api_base.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._timeout = timeout

    # ── BaseLLMProvider ─────────────────────────────────────

    @property
    def is_available(self) -> bool:
        return bool(self._api_key)

    @property
    def name(self) -> str:
        return f"openai_compatible({self._model})"

    def generate(self, prompt: str, **kwargs: Any) -> LLMResult:
        if not self._api_key:
            return LLMResult(text="", error="API key not configured")

        url = f"{self._api_base}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        payload = {
            "model": self._model,
            "messages": [
                {"role": "user", "content": prompt},
            ],
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }

        log.info("Calling OpenAI-compatible API: %s model=%s", self._api_base, self._model)

        try:
            with httpx.Client(timeout=self._timeout) as client:
                from live2note.llm.utils import call_with_retry

                resp = call_with_retry(
                    lambda: client.post(url, json=payload, headers=headers),
                )
        except httpx.HTTPError as exc:
            log.error("API request failed: %s", exc)
            return LLMResult(text="", error=str(exc))

        body = resp.json()
        choices = body.get("choices", [])
        if not choices:
            return LLMResult(text="", error="No choices in API response")

        content = choices[0].get("message", {}).get("content", "")
        return LLMResult(text=content, raw=body)
