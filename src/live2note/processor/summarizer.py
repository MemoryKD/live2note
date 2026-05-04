"""LLM-based chunk summarization using OpenAI-compatible API."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from live2note.logger import get_logger
from live2note.processor.chunker import Chunk
from live2note.prompts import CHUNK_PROMPT_TEMPLATE, SYSTEM_PROMPT

log = get_logger("processor.summarizer")


@dataclass
class ChunkSummary:
    chunk_id: int
    start: float
    end: float
    summary: str
    key_points: list[str]
    knowledge_points: list[str]
    action_items: list[str]
    tags: list[str]
    keywords: list[str]
    important_quotes: list[str]


_EMPTY_SUMMARY: dict[str, Any] = {
    "summary": "",
    "key_points": [],
    "knowledge_points": [],
    "action_items": [],
    "tags": [],
    "keywords": [],
    "important_quotes": [],
}


class Summarizer:
    """Calls an OpenAI-compatible chat API to extract knowledge from chunks."""

    def __init__(
        self,
        api_base: str = "https://api.openai.com/v1",
        api_key: str = "",
        model: str = "gpt-4o",
        temperature: float = 0.3,
        max_tokens: int = 4096,
        summary_model: str = "",
    ) -> None:
        self._api_base = api_base.rstrip("/")
        self._api_key = api_key
        self._model = summary_model or model
        self._temperature = temperature
        self._max_tokens = max_tokens

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    def summarize(self, chunk: Chunk) -> ChunkSummary:
        """Summarize a single chunk. Raises if API key is missing."""
        if not self._api_key:
            raise ValueError(
                "LLM API key not configured. "
                "Set llm.api_key in config.yaml or LLM_API_KEY env var."
            )

        prompt = CHUNK_PROMPT_TEMPLATE.format(text=chunk.text)
        raw = self._call_api(prompt)
        data = self._parse_response(raw)

        return ChunkSummary(
            chunk_id=chunk.chunk_id,
            start=chunk.start,
            end=chunk.end,
            summary=data.get("summary", ""),
            key_points=data.get("key_points", []),
            knowledge_points=data.get("knowledge_points", []),
            action_items=data.get("action_items", []),
            tags=data.get("tags", []),
            keywords=data.get("keywords", []),
            important_quotes=data.get("important_quotes", []),
        )

    # ── internal ─────────────────────────────────────────────

    def _call_api(self, user_prompt: str) -> str:
        import httpx

        url = f"{self._api_base}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }

        log.info("Calling LLM: %s (model=%s)", url, self._model)

        with httpx.Client(timeout=120) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()

        body = resp.json()
        content = body["choices"][0]["message"]["content"]
        return content

    @staticmethod
    def _parse_response(raw: str) -> dict[str, Any]:
        """Extract JSON from LLM response, handling markdown fences."""
        text = raw.strip()
        # Strip ```json ... ``` fences if present.
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [
                line for line in lines
                if not line.strip().startswith("```")
            ]
            text = "\n".join(lines)

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            log.warning("Failed to parse LLM response as JSON, using raw text as summary.")
            return {**_EMPTY_SUMMARY, "summary": text[:500]}
