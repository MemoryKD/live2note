"""LLM provider abstraction layer."""

from live2note.llm.anthropic_provider import AnthropicProvider
from live2note.llm.base import BaseLLMProvider, LLMResult
from live2note.llm.env_detector import detect_env, detect_provider, mask_key
from live2note.llm.external_cli import ExternalCLIProvider, detect_external_cli
from live2note.llm.openai_compatible import OpenAICompatibleProvider
from live2note.llm.prompt_only import PromptOnlyProvider
from live2note.llm.provider_registry import create_provider

__all__ = [
    "BaseLLMProvider",
    "LLMResult",
    "AnthropicProvider",
    "ExternalCLIProvider",
    "OpenAICompatibleProvider",
    "PromptOnlyProvider",
    "create_provider",
    "detect_env",
    "detect_provider",
    "detect_external_cli",
    "mask_key",
]
