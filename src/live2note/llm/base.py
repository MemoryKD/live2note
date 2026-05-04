"""Base LLM provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LLMResult:
    """Unified result from any LLM provider."""

    text: str
    raw: str = ""
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseLLMProvider(ABC):
    """Abstract interface for LLM providers.

    Implementations: OpenAI-compatible API, Anthropic API, external CLI, prompt-only.
    """

    @abstractmethod
    def generate(self, prompt: str, **kwargs: Any) -> LLMResult:
        """Send a prompt to the LLM and return the result.

        Args:
            prompt: The full prompt text (system + user).
            **kwargs: Provider-specific options (task_id, metadata, etc.)

        Returns:
            LLMResult with the generated text.
        """

    @property
    def is_available(self) -> bool:
        """Return True if this provider can be used right now."""
        return True

    @property
    def name(self) -> str:
        return self.__class__.__name__
