"""Platform adapters."""

from live2note.adapters.base import BaseAdapter
from live2note.adapters.registry import get_adapter, get_adapter_or_raise, list_adapters

__all__ = [
    "BaseAdapter",
    "get_adapter",
    "get_adapter_or_raise",
    "list_adapters",
]
