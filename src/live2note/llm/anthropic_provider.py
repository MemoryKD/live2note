"""Anthropic API provider."""

from __future__ import annotations

from typing import Any

import httpx

from live2note.llm.base import BaseLLMProvider, LLMResult
from live2note.logger import get_logger

log = get_logger("llm.anthropic")


class AnthropicProvider(BaseLLMProvider):
    """Calls the Anthropic Messages API.

    Requires ANTHROPIC_API_KEY environment variable.
    Uses the native Anthropic API format, not OpenAI-compatible.
    """

    def __init__(
        self,
        api_key: str = "",
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 4096,
        timeout: int = 120,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._max_tokens = max_tokens
        self._timeout = timeout

    @property
    def is_available(self) -> bool:
        return bool(self._api_key)

    @property
    def name(self) -> str:
        return f"anthropic({self._model})"

    def generate(self, prompt: str, **kwargs: Any) -> LLMResult:
        if not self._api_key:
            return LLMResult(text="", error="ANTHROPIC_API_KEY not configured")

        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
        }
        payload = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": [
                {"role": "user", "content": prompt},
            ],
        }

        log.info("Calling Anthropic API: model=%s", self._model)

        try:
            with httpx.Client(timeout=self._timeout) as client:
                from live2note.llm.utils import call_with_retry

                resp = call_with_retry(
                    lambda: client.post(url, json=payload, headers=headers),
                )
        except httpx.HTTPError as exc:
            log.error("Anthropic API request failed: %s", exc)
            return LLMResult(text="", error=str(exc))

        body = resp.json()

        # Extract text from content blocks.
        content_blocks = body.get("content", [])
        text_parts = []
        for block in content_blocks:
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))

        return LLMResult(
            text="\n".join(text_parts),
            raw=str(body),
        )
