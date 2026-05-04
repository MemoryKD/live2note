"""Platform adapter base class."""

from __future__ import annotations

from abc import ABC, abstractmethod

from live2note.models.task import CheckResult


class BaseAdapter(ABC):
    """Abstract base for platform adapters.

    Each adapter is responsible for:
    - Matching URLs that belong to its platform.
    - Detecting live status and extracting metadata.
    - Resolving a recordable stream URL.
    """

    @abstractmethod
    def match(self, url: str) -> bool:
        """Return True if this adapter handles the given URL."""

    @abstractmethod
    def get_platform(self) -> str:
        """Return the platform name, e.g. 'bilibili', 'douyin', 'generic'."""

    def get_source_type(self, url: str) -> str:
        """Return source type for URL classification. Defaults to platform name."""
        return self.get_platform()

    @abstractmethod
    def check_live(self, url: str) -> CheckResult:
        """Check live status and return a CheckResult with metadata."""

    def get_metadata(self, url: str) -> dict[str, str]:
        """Return raw metadata dict. Default delegates to check_live."""
        result = self.check_live(url)
        return {
            "platform": result.platform,
            "title": result.title,
            "streamer": result.streamer,
            "room_id": result.room_id,
            "stream_url": result.stream_url,
            "is_live": str(result.is_live),
        }

    def resolve_stream_url(self, url: str) -> str:
        """Resolve a recordable stream URL. Default delegates to check_live."""
        result = self.check_live(url)
        return result.stream_url
