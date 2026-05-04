"""Prompt-only provider — exports prompts to files for manual processing.

No API key is needed. The user can copy prompt files to any LLM or agent,
then import the results back via live2note export-summary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from live2note.llm.base import BaseLLMProvider, LLMResult
from live2note.logger import get_logger

log = get_logger("llm.prompt_only")

_PENDING_MARKER = "pending_manual_summary"


class PromptOnlyProvider(BaseLLMProvider):
    """Writes each prompt to a file instead of calling an API.

    Returns LLMResult with a marker indicating manual processing is needed.
    """

    def __init__(self, output_dir: Path | None = None) -> None:
        self._output_dir = output_dir

    @property
    def is_available(self) -> bool:
        return True

    @property
    def name(self) -> str:
        return "prompt_only"

    def generate(self, prompt: str, **kwargs: Any) -> LLMResult:
        chunk_id = kwargs.get("chunk_id", "unknown")
        suffix = kwargs.get("suffix", "chunk")

        if self._output_dir:
            self._output_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{suffix}_{chunk_id:03d}_prompt.md"
            filepath = self._output_dir / filename
            filepath.write_text(prompt, encoding="utf-8")
            log.info("Prompt saved: %s", filepath)

        return LLMResult(
            text="",
            error=_PENDING_MARKER,
            metadata={"chunk_id": chunk_id, "suffix": suffix},
        )
