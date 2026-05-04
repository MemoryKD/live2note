"""Chunk summarization using LLM providers.

The Summarizer delegates to a BaseLLMProvider and parses the response.
It does not care whether the provider is OpenAI, Anthropic, external CLI, or prompt-only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from live2note.llm.base import BaseLLMProvider, LLMResult
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

_PENDING_MARKER = "pending_manual_summary"


class Summarizer:
    """Summarizes chunks using any BaseLLMProvider.

    The provider is injected — no direct API calls are made here.
    """

    def __init__(self, provider: BaseLLMProvider) -> None:
        self._provider = provider

    @property
    def is_configured(self) -> bool:
        return self._provider.is_available

    @property
    def provider_name(self) -> str:
        return self._provider.name

    def summarize(self, chunk: Chunk, task_id: str | None = None) -> ChunkSummary:
        """Summarize a single chunk using the configured provider."""
        prompt = CHUNK_PROMPT_TEMPLATE.format(text=chunk.text)
        full_prompt = f"{SYSTEM_PROMPT}\n\n{prompt}"

        result: LLMResult = self._provider.generate(
            full_prompt,
            chunk_id=chunk.chunk_id,
            suffix="chunk",
            task_id=task_id,
        )

        if result.error and not result.text:
            if result.error == _PENDING_MARKER:
                return ChunkSummary(
                    chunk_id=chunk.chunk_id,
                    start=chunk.start,
                    end=chunk.end,
                    summary=_PENDING_MARKER,
                    key_points=[],
                    knowledge_points=[],
                    action_items=[],
                    tags=[],
                    keywords=[],
                    important_quotes=[],
                )
            return ChunkSummary(
                chunk_id=chunk.chunk_id,
                start=chunk.start,
                end=chunk.end,
                summary=f"[Error: {result.error}]",
                key_points=[],
                knowledge_points=[],
                action_items=[],
                tags=[],
                keywords=[],
                important_quotes=[],
            )

        data = self._parse_response(result.text)

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

    @staticmethod
    def _parse_response(raw: str) -> dict[str, Any]:
        """Extract JSON from LLM response, handling markdown fences."""
        text = raw.strip()
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
