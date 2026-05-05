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
        """Extract JSON from LLM response, handling truncation and markdown fences."""
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [
                line for line in lines
                if not line.strip().startswith("```")
            ]
            text = "\n".join(lines)

        # 1) Try direct JSON parse.
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 2) Try to fix truncated JSON: find structural end.
        fixed = _try_fix_truncated_json(text)
        if fixed is not None:
            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                pass

        # 3) Regex fallback — extract known fields from semi-structured text.
        result = _extract_json_regex(text)
        if result is not None:
            log.warning("LLM response was not valid JSON, used regex fallback.")
            return result

        # 4) Last resort — store raw text as summary.
        log.warning("Failed to parse LLM response as JSON, using raw text as summary.")
        return {**_EMPTY_SUMMARY, "summary": text[:500]}


def _try_fix_truncated_json(text: str) -> str | None:
    """Attempt to close an unclosed JSON object/array."""
    # Strip trailing whitespace and incomplete lines.
    # Keep only complete lines (ending with a comma, bracket, or brace).
    lines = text.split("\n")
    clean_lines = []
    for line in lines:
        stripped = line.rstrip()
        if not stripped:
            continue
        clean_lines.append(stripped)

    if not clean_lines:
        return None

    # Remove trailing incomplete lines (last line shouldn't end with
    # a value continuation character unless it's a bracket/brace/comma).
    joined = "\n".join(clean_lines)
    # Try progressively shorter endings.
    for end in ["]", "}", '",', "]", "}", '"']:
        if end in ["]", "}"]:
            candidate = joined.rstrip(",") + end
        elif end == '"':
            candidate = joined.rstrip(",") + '"'
        else:
            candidate = joined.rstrip(",").rstrip('"') + '"' + end
        # Count braces and brackets to guess what's missing.
        opens = candidate.count("{") + candidate.count("[")
        closes = candidate.count("}") + candidate.count("]")
        if opens <= closes:
            return candidate  # already balanced or over-closed
        missing = opens - closes
        # Guess: missing are all braces (most common case for this domain).
        candidate = candidate.rstrip(",") + "}" * missing
        if opens <= missing + closes:
            return candidate

    return None


def _extract_json_regex(text: str) -> dict[str, Any] | None:
    """Extract structured fields from LLM response using regex."""
    import re

    result: dict[str, Any] = dict(_EMPTY_SUMMARY)
    any_found = False

    # Extract "summary" value (single string).
    m = re.search(r'"summary"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.DOTALL)
    if m:
        result["summary"] = m.group(1).replace('\\"', '"')
        any_found = True

    # Extract array fields: key_points, knowledge_points, action_items, tags, keywords, important_quotes.
    for field in [
        "key_points",
        "knowledge_points",
        "action_items",
        "tags",
        "keywords",
        "important_quotes",
    ]:
        items = _extract_string_array(text, field)
        if items is not None:
            result[field] = items
            any_found = True

    return result if any_found else None


def _extract_string_array(text: str, field: str) -> list[str] | None:
    """Extract a JSON string array for a given field name, handling truncation."""
    import re

    m = re.search(rf'"{field}"\s*:\s*\[(.*?)(?:\]|$)', text, re.DOTALL)
    if not m:
        return None

    content = m.group(1).strip()
    if not content:
        return []

    # Extract individual quoted strings (may be incomplete).
    items: list[str] = []
    for sm in re.finditer(r'"((?:[^"\\]|\\.)*)"', content):
        items.append(sm.group(1).replace('\\"', '"'))
    return items
