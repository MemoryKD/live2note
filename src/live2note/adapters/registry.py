"""Adapter registry — auto-detect platform from URL, or select by name."""

from __future__ import annotations

from live2note.adapters.base import BaseAdapter
from live2note.adapters.bilibili import BilibiliAdapter
from live2note.adapters.douyin import DouyinAdapter
from live2note.adapters.generic import GenericStreamAdapter
from live2note.logger import get_logger

log = get_logger("adapter.registry")

# Order matters — generic must be last as the fallback.
_ADAPTERS: list[BaseAdapter] = [
    BilibiliAdapter(),
    DouyinAdapter(),
    GenericStreamAdapter(),
]

_NAME_MAP: dict[str, BaseAdapter] = {
    a.get_platform(): a for a in _ADAPTERS
}


def get_adapter(url: str) -> BaseAdapter | None:
    """Return the first adapter whose match() returns True, or None."""
    for adapter in _ADAPTERS:
        if adapter.match(url):
            log.debug("URL matched adapter: %s", adapter.get_platform())
            return adapter
    return None


def get_adapter_by_name(name: str) -> BaseAdapter | None:
    """Return adapter by explicit platform name, e.g. 'bilibili'."""
    return _NAME_MAP.get(name.lower())


def get_adapter_or_raise(url: str, platform: str = "auto") -> BaseAdapter:
    """Return the adapter for the given URL/platform.

    If platform is 'auto', uses URL matching.
    If platform is a specific name, returns that adapter.
    Raises ValueError if no adapter is found.
    """
    if platform != "auto":
        adapter = get_adapter_by_name(platform)
        if adapter is None:
            available = ", ".join(sorted(_NAME_MAP.keys()))
            raise ValueError(
                f"Unknown platform '{platform}'. Available: {available}"
            )
        return adapter

    adapter = get_adapter(url)
    if adapter is None:
        raise ValueError(
            f"No adapter found for URL: {url}\n"
            "Try specifying --platform explicitly."
        )
    return adapter


def list_adapters() -> list[str]:
    """Return all registered platform names."""
    return sorted(_NAME_MAP.keys())


def configure_adapter(platform: str, platform_config: dict) -> None:
    """Apply platform-specific config to a registered adapter."""
    adapter = _NAME_MAP.get(platform)
    if adapter is None:
        log.warning("Cannot configure unknown platform: %s", platform)
        return
    if hasattr(adapter, "configure"):
        adapter.configure(platform_config)
