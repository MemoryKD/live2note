"""Generic stream adapter for direct m3u8/flv/rtmp/http stream URLs."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from live2note.adapters.base import BaseAdapter
from live2note.logger import get_logger
from live2note.models.task import CheckResult

log = get_logger("adapter.generic")

# Patterns that indicate a direct streamable URL (not a web page).
_RTMP_RE = re.compile(r"^rtmp", re.IGNORECASE)
_STREAM_EXT_RE = re.compile(r"\.(m3u8|flv|mpd|ts|m4a|mp3)(\?|$)", re.IGNORECASE)
_HTTP_STREAM_HINTS = re.compile(
    r"(hls|stream|pull|play)", re.IGNORECASE
)


def is_stream_url(url: str) -> bool:
    """Heuristic: does this URL point directly to a media stream?"""
    if _RTMP_RE.match(url):
        return True
    parsed = urlparse(url)
    path = parsed.path
    if _STREAM_EXT_RE.search(path):
        return True
    # HTTP(S) URLs with stream-related path segments and no HTML-like extension.
    # Only match hints in the path, not the host — avoids false positives on
    # domains like live.bilibili.com or live.douyin.com.
    if parsed.scheme in ("http", "https") and _HTTP_STREAM_HINTS.search(path):
        if not re.search(r"\.(html?|php|asp|jsp)(\?|$)", path, re.IGNORECASE):
            return True
    return False


class GenericStreamAdapter(BaseAdapter):
    """Handles direct stream URLs: m3u8, flv, rtmp, http stream."""

    def match(self, url: str) -> bool:
        return is_stream_url(url)

    def get_platform(self) -> str:
        return "generic"

    def check_live(self, url: str) -> CheckResult:
        parsed = urlparse(url)
        stream_type = "unknown"
        if _RTMP_RE.match(url):
            stream_type = "rtmp"
        elif ".m3u8" in parsed.path.lower():
            stream_type = "hls"
        elif ".flv" in parsed.path.lower():
            stream_type = "flv"
        elif ".mpd" in parsed.path.lower():
            stream_type = "dash"
        elif parsed.scheme in ("http", "https"):
            stream_type = "http"

        # For direct stream URLs we cannot reliably detect live status
        # without actually connecting. Assume live — the recorder will
        # fail fast if the stream is down.
        log.info("Generic stream detected: %s (%s)", stream_type, url[:80])

        return CheckResult(
            platform="generic",
            is_live=True,
            title=f"{stream_type} stream",
            streamer="",
            stream_url=url,
            room_id=parsed.path.split("/")[-1] or url,
        )
