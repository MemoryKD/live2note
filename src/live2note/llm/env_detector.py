"""Environment variable detection for LLM configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass

from live2note.logger import get_logger

log = get_logger("llm.env")


@dataclass(frozen=True)
class EnvResult:
    provider: str                    # "openai_compatible" | "anthropic"
    api_key: str = ""
    api_base: str = ""
    model: str = ""


_KEY_VARS: list[str] = [
    "LIVE2NOTE_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "OPENROUTER_API_KEY",
    "MIMO_API_KEY",
]

_BASE_URL_VARS: list[str] = [
    "LIVE2NOTE_BASE_URL",
    "OPENAI_BASE_URL",
]

_MODEL_VARS: list[str] = [
    "LIVE2NOTE_MODEL",
]


# ── Public API ──────────────────────────────────────────────


def detect_env() -> EnvResult:
    """Scan environment variables and return the first available LLM config.

    Returns EnvResult with empty api_key if nothing is found.
    """
    api_key = _find_first_key(_KEY_VARS)
    api_base = _find_first_key(_BASE_URL_VARS)
    model = _find_first_key(_MODEL_VARS)

    if not api_key:
        return EnvResult(provider="none")

    provider = _detect_provider(api_key, api_base)
    return EnvResult(
        provider=provider,
        api_key=api_key,
        api_base=api_base,
        model=model,
    )


def detect_api_key() -> str:
    """Return the first available API key from known env vars."""
    return _find_first_key(_KEY_VARS)


def detect_provider() -> str:
    """Detect which LLM provider is available based on env vars.

    Returns: "openai_compatible" | "anthropic" | "none"
    """
    key = detect_api_key()
    return _detect_provider(key)


def mask_key(key: str) -> str:
    """Mask an API key for safe logging. Shows first 4 and last 4 chars."""
    if not key or len(key) < 12:
        return "****"
    return key[:4] + "****" + key[-4:]


def _find_first_key(vars: list[str]) -> str:
    for var in vars:
        val = os.environ.get(var, "").strip()
        if val:
            return val
    return ""


def _detect_provider(api_key: str, api_base: str = "") -> str:
    if not api_key:
        return "none"
    # Anthropic keys start with sk-ant-.
    if api_key.startswith("sk-ant-"):
        return "anthropic"
    return "openai_compatible"
