"""Bilibili live adapter — uses yt-dlp for public metadata extraction."""

from __future__ import annotations

import re

from live2note.adapters.base import BaseAdapter
from live2note.logger import get_logger
from live2note.models.task import CheckResult, LiveCheckStatus
from live2note.resolvers.ytdlp_resolver import YtdlpError as _YtdlpError

log = get_logger("adapter.bilibili")

_ROOM_URL_RE = re.compile(r"live\.bilibili\.com/(\d+)")
_B23_RE = re.compile(r"b23\.tv/")


class BilibiliAdapter(BaseAdapter):
    """Bilibili live stream adapter.

    Supports:
      - https://live.bilibili.com/<room_id>
      - b23.tv short links are noted but not resolved yet.
    """

    def match(self, url: str) -> bool:
        if _B23_RE.search(url):
            return False  # Short links need redirect resolution; mark as unsupported.
        return bool(_ROOM_URL_RE.search(url))

    def get_platform(self) -> str:
        return "bilibili"

    def check_live(self, url: str) -> CheckResult:
        m = _ROOM_URL_RE.search(url)
        if not m:
            return CheckResult(
                platform="bilibili",
                is_live=False,
                error="Cannot parse Bilibili room ID from URL.",
            )

        room_id = m.group(1)
        canonical = f"https://live.bilibili.com/{room_id}"

        # Attempt yt-dlp extraction (public access only).
        try:
            info = self._yt_dlp_info(canonical)
        except _YtdlpError as exc:
            log.warning("yt-dlp failed for %s: %s", canonical, exc)
            return CheckResult(
                platform="bilibili",
                is_live=False,
                live_status=LiveCheckStatus.ERROR.value,
                room_id=room_id,
                error=f"yt-dlp error: {exc}",
            )

        title = info.get("title", "")
        streamer = info.get("uploader", info.get("creator", ""))
        is_live = info.get("is_live", False) or info.get("live_status") == 1
        stream_url = info.get("url", "")
        thumbnail = info.get("thumbnail", "")

        # If yt-dlp gave us a direct stream URL, use it.
        # Otherwise we'll need to extract from formats later.
        if not stream_url and info.get("formats"):
            # Pick the best format.
            best = info["formats"][-1]
            stream_url = best.get("url", "")

        log.info(
            "Bilibili room %s: live=%s, title=%s",
            room_id,
            is_live,
            title[:60] if title else "(empty)",
        )

        live_status = LiveCheckStatus.LIVE.value if is_live else LiveCheckStatus.NOT_LIVE.value

        return CheckResult(
            platform="bilibili",
            is_live=is_live,
            live_status=live_status,
            title=title,
            streamer=streamer,
            stream_url=stream_url,
            room_id=room_id,
            cover_url=thumbnail,
            error=None if is_live else "Stream is not currently live.",
        )

    # ── yt-dlp subprocess ────────────────────────────────────

    @staticmethod
    def _yt_dlp_info(url: str, timeout: int = 30) -> dict:
        """Run yt-dlp -j and return parsed JSON. Raises _YtdlpError on failure."""
        from live2note.resolvers.ytdlp_resolver import run_ytdlp

        return run_ytdlp(url, timeout=timeout)
