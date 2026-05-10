"""Unified stream resolution result model."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ResolveStatus(str, Enum):
    RESOLVED = "resolved"
    NOT_LIVE = "not_live"
    EXPIRED = "expired"
    ERROR = "error"
    MANUAL_REQUIRED = "manual_required"


class ResolveStrategy(str, Enum):
    USER_OVERRIDE = "user_override"
    YT_DLP = "yt_dlp"
    STREAMLINK = "streamlink"
    PAGE_PUBLIC_DATA = "page_public_data"
    METADATA_CACHE = "metadata_cache"
    NONE = "none"


@dataclass(frozen=True)
class ResolveResult:
    """Result of attempting to resolve a recordable stream URL.

    Distinct from CheckResult: CheckResult describes liveness;
    ResolveResult describes whether a stream URL was successfully obtained.
    """

    platform: str
    source_url: str
    status: str = ResolveStatus.ERROR.value
    strategy: str = ResolveStrategy.NONE.value
    stream_url: str = ""
    is_live: bool | None = None
    title: str = ""
    streamer: str = ""
    room_id: str = ""
    stream_format: str = ""
    expires_at: str | None = None
    stream_url_ttl: int = 3600
    error_message: str = ""
    debug_info: dict[str, Any] = field(default_factory=dict)

    @property
    def is_resolved(self) -> bool:
        return self.status == ResolveStatus.RESOLVED.value and bool(self.stream_url)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict. Never includes full stream_url in serialization."""
        return {
            "platform": self.platform,
            "source_url": self.source_url,
            "status": self.status,
            "strategy": self.strategy,
            "is_live": self.is_live,
            "title": self.title,
            "streamer": self.streamer,
            "room_id": self.room_id,
            "stream_format": self.stream_format,
            "expires_at": self.expires_at,
            "stream_url_ttl": self.stream_url_ttl,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResolveResult:
        known = {k for k in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})
