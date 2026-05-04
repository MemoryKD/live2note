"""LLM provider registry — factory for creating providers from config.

Default provider is external_cli. API key modes require explicit opt-in.
"""

from __future__ import annotations

from live2note.llm.anthropic_provider import AnthropicProvider
from live2note.llm.base import BaseLLMProvider, LLMResult
from live2note.llm.env_detector import detect_env, mask_key
from live2note.llm.external_cli import ExternalCLIProvider, detect_external_cli
from live2note.llm.openai_compatible import OpenAICompatibleProvider
from live2note.llm.prompt_only import PromptOnlyProvider
from live2note.logger import get_logger

log = get_logger("llm.registry")


class _NoneProvider(BaseLLMProvider):
    """Fallback provider when nothing is configured — always returns empty."""

    @property
    def name(self) -> str:
        return "none"

    def generate(self, prompt: str, **kwargs) -> LLMResult:
        return LLMResult(text="", error="No LLM provider configured")


def _build_external_cli(config_llm) -> ExternalCLIProvider | None:
    """Build an ExternalCLIProvider from config, with auto-detection fallback."""
    ec = getattr(config_llm, "external_cli", {}) or {}

    if ec.get("enabled") and ec.get("command"):
        log.info("LLM provider: external_cli (%s %s)",
                 ec["command"], " ".join(ec.get("args", [])))
        return ExternalCLIProvider(
            command=ec["command"],
            args=ec.get("args", []),
            timeout_seconds=ec.get("timeout_seconds", 600),
            input_mode=ec.get("input_mode", "stdin"),
            working_dir=ec.get("working_dir", ""),
            fallback_to_prompt_only=ec.get("fallback_to_prompt_only", True),
        )

    # Auto-detect external CLI command in PATH.
    auto_cmd = detect_external_cli()
    if auto_cmd:
        log.info("LLM provider: external_cli (auto-detected: %s)", auto_cmd)
        return ExternalCLIProvider(command=auto_cmd)

    return None


def _build_api_provider(config_llm, provider_name: str) -> BaseLLMProvider | None:
    """Build an API-based provider (openai_compatible or anthropic).

    Only used when user explicitly enables these modes.
    provider_name is the resolved provider name (from config or override).
    """
    if provider_name not in ("openai_compatible", "anthropic"):
        return None

    env = detect_env()
    api_key = env.api_key or (getattr(config_llm, "api_key", "") or "")

    api_base = (
        env.api_base
        or (getattr(config_llm, "api_base", "") or "")
        or "https://api.openai.com/v1"
    )
    model = (
        env.model
        or (getattr(config_llm, "model", "") or "")
        or "gpt-4o"
    )

    if provider_name == "anthropic" and api_key:
        log.info("LLM provider: anthropic (key=%s)", mask_key(api_key))
        return AnthropicProvider(
            api_key=api_key,
            model=model,
            max_tokens=getattr(config_llm, "max_tokens", 4096),
        )

    if provider_name == "openai_compatible" and api_key:
        log.info("LLM provider: openai_compatible base=%s model=%s key=%s",
                 api_base, model, mask_key(api_key))
        return OpenAICompatibleProvider(
            api_base=api_base,
            api_key=api_key,
            model=model,
            temperature=getattr(config_llm, "temperature", 0.3),
            max_tokens=getattr(config_llm, "max_tokens", 4096),
        )

    log.warning("%s configured but no API key found — falling back.", provider_name)
    return None


def _build_prompt_only(config_llm, output_dir=None) -> PromptOnlyProvider | None:
    """Build a PromptOnlyProvider as fallback."""
    po = getattr(config_llm, "prompt_only", {}) or {}
    if po.get("enabled") or output_dir:
        od = output_dir or po.get("output_dir", "prompts")
        log.info("LLM provider: prompt_only (output_dir=%s)", od)
        return PromptOnlyProvider(output_dir=od)
    return None


def create_provider(config_llm, output_dir=None, provider_override: str = "") -> BaseLLMProvider:
    """Create the appropriate LLM provider based on config.

    Resolution order (new default behavior):
      1. provider_override (CLI --provider flag)
      2. Explicit openai_compatible / anthropic → API mode (user opt-in)
      3. Explicit external_cli → ExternalCLIProvider
      4. Default (external_cli) → auto-detect or fallback
      5. Fallback to prompt_only
      6. Fallback to none (no-op)
    """
    provider_name = provider_override or (
        getattr(config_llm, "provider", "external_cli") or "external_cli"
    )

    log.info("LLM provider requested: %s", provider_name)

    # Explicit "none" — skip LLM entirely.
    if provider_name == "none":
        log.info("LLM provider: none")
        return _NoneProvider()

    # Explicit API modes — user opt-in only.
    if provider_name in ("openai_compatible", "anthropic"):
        api_provider = _build_api_provider(config_llm, provider_name)
        if api_provider:
            return api_provider
        # API provider failed — fall through to fallback.

    # External CLI (explicit or default).
    if provider_name in ("external_cli", "auto"):
        ec_provider = _build_external_cli(config_llm)
        if ec_provider:
            return ec_provider

        log.warning(
            "External CLI not available: no command found in PATH. "
            "Falling back to prompt_only."
        )

    # Fallback: prompt_only.
    po_provider = _build_prompt_only(config_llm, output_dir)
    if po_provider:
        return po_provider

    # Last resort.
    log.info("LLM provider: none (no config available)")
    return _NoneProvider()
