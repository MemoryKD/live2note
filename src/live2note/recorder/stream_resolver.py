"""Resolve a recordable stream URL from user input or adapter metadata."""

from __future__ import annotations

from live2note.adapters.base import BaseAdapter
from live2note.logger import get_logger
from live2note.models.task import TaskState
from live2note.utils.safe_url import safe_url

log = get_logger("recorder.resolve")


class StreamResolver:
    """Determines the actual stream URL to record from.

    Priority:
      1. Explicit --stream-url from user
      2. stream_url already in task metadata (from adapter check)
      3. adapter.resolve_stream_url(page_url)
    """

    def resolve(
        self,
        state: TaskState,
        adapter: BaseAdapter,
        stream_url_override: str = "",
    ) -> str:
        # 1. User-provided override.
        if stream_url_override:
            log.info("Using explicit stream URL: %s", safe_url(stream_url_override))
            return stream_url_override

        # 2. Already resolved during check_live.
        if state.metadata.stream_url:
            log.info(
                "Using stream URL from metadata: %s",
                safe_url(state.metadata.stream_url),
            )
            return state.metadata.stream_url

        # 3. Ask adapter to resolve now.
        log.info("Resolving stream URL via adapter: %s", adapter.get_platform())
        url = adapter.resolve_stream_url(state.url)
        if not url:
            raise ValueError(
                f"Could not resolve stream URL for {state.url}.\n"
                "Try specifying --stream-url directly."
            )
        log.info("Resolved stream URL: %s", safe_url(url))
        return url
