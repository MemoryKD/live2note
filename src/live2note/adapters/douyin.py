"""Douyin live adapter — uses yt-dlp and streamlink for stream resolution."""

from __future__ import annotations

import json
import re
import subprocess

from live2note.adapters.base import BaseAdapter
from live2note.logger import get_logger
from live2note.models.task import CheckResult, LiveCheckStatus

log = get_logger("adapter.douyin")

# Matches:
#   https://live.douyin.com/<room_id>
#   https://www.douyin.com/root/live/<room_id>
#   https://www.douyin.com/<room_id>  (sometimes redirects to live)
_DOUYIN_LIVE_RE = re.compile(
    r"(?:live\.douyin\.com|douyin\.com/(?:root/)?live)[/](\d+)"
)
_DOUYIN_ROOM_RE = re.compile(r"douyin\.com/(\d{5,})")


class DouyinAdapter(BaseAdapter):
    """Douyin live stream adapter.

    Supports:
      - https://live.douyin.com/<room_id>
      - https://www.douyin.com/root/live/<room_id>

    Uses multi-level resolution: --stream-url override > yt-dlp > streamlink > manual.
    v.douyin.com short links are recognised but not resolved.
    """

    def __init__(self) -> None:
        self._resolver: object = None  # Lazy-init DouyinResolver

    def match(self, url: str) -> bool:
        # v.douyin.com short links and webcast.amemv.com reflow pages
        if "v.douyin.com" in url or "webcast.amemv.com" in url:
            return True
        return bool(_DOUYIN_LIVE_RE.search(url) or _DOUYIN_ROOM_RE.search(url))

    def get_platform(self) -> str:
        return "douyin"

    def get_source_type(self, url: str) -> str:
        if "v.douyin.com" in url:
            return "douyin_shortlink"
        return "douyin"

    def check_live(self, url: str) -> CheckResult:
        m = _DOUYIN_LIVE_RE.search(url)
        if m:
            room_id = m.group(1)
        else:
            m2 = _DOUYIN_ROOM_RE.search(url)
            if m2:
                room_id = m2.group(1)
            else:
                # For v.douyin.com and webcast.amemv.com, use a placeholder —
                # the resolver will extract the real room_id from redirects.
                if "v.douyin.com" in url or "webcast.amemv.com" in url:
                    return self._check_live_via_resolver(url, "unknown")
                return CheckResult(
                    platform="douyin",
                    is_live=False,
                    live_status=LiveCheckStatus.UNKNOWN.value,
                    error="Cannot parse Douyin room ID from URL.",
                )

        # v.douyin.com short links — delegate to DouyinResolver page parser.
        if "v.douyin.com" in url:
            return self._check_live_via_resolver(url, room_id)

        canonical = f"https://live.douyin.com/{room_id}"

        # Primary: use DouyinResolver (tries yt-dlp → streamlink → page data → check_live).
        result = self._check_live_via_resolver(url, room_id)
        if result.stream_url:
            return result

        # Fallback: direct yt-dlp (backward compat, keeps existing mock tests working).
        try:
            info = self._yt_dlp_info(canonical)
        except _YtdlpError as exc:
            log.warning("yt-dlp failed for %s: %s", canonical, exc)
            return CheckResult(
                platform="douyin",
                is_live=False,
                live_status=LiveCheckStatus.ERROR.value,
                room_id=room_id,
                error=(
                    f"yt-dlp error: {exc}\n"
                    "Douyin may require browser JS. Try:\n"
                    "  1. Run: live2note resolve <url> --platform douyin\n"
                    "  2. Or provide a direct stream URL with --stream-url.\n"
                    "  3. Install streamlink: pip install streamlink"
                ),
            )

        title = info.get("title", "")
        streamer = info.get("uploader", info.get("creator", ""))
        is_live = info.get("is_live", False) or info.get("live_status") == 1
        stream_url = info.get("url", "")
        thumbnail = info.get("thumbnail", "")

        if not stream_url and info.get("formats"):
            best = info["formats"][-1]
            stream_url = best.get("url", "")

        return CheckResult(
            platform="douyin",
            is_live=is_live,
            live_status=LiveCheckStatus.LIVE.value if is_live else LiveCheckStatus.NOT_LIVE.value,
            title=title,
            streamer=streamer,
            stream_url=stream_url,
            room_id=room_id,
            cover_url=thumbnail,
            error=None if is_live else "Stream is not currently live.",
        )

    def resolve_stream_url(self, url: str, stream_url_override: str = "") -> str:
        """Resolve recordable stream URL using the multi-level DouyinResolver.

        Overrides BaseAdapter.resolve_stream_url() to use DouyinResolver's
        multilevel strategy instead of delegating to check_live().
        """
        if stream_url_override:
            return stream_url_override
        return self._get_resolver().resolve_stream_url(url, stream_url_override="")

    # ── resolver helpers ─────────────────────────────────────

    def _check_live_via_resolver(self, url: str, room_id: str) -> CheckResult:
        """Use DouyinResolver (including page parser) to check liveness."""
        try:
            resolver = self._get_resolver()
            result = resolver.check_live(url)
            log.info("Douyin room %s: live=%s (via resolver), title=%s",
                     room_id, result.is_live,
                     result.title[:60] if result.title else "(empty)")
            # Ensure display_title is populated.
            if not result.title or result.title == "":
                result = CheckResult(
                    platform="douyin",
                    is_live=result.is_live,
                    live_status=result.live_status,
                    title="抖音直播",
                    streamer=result.streamer or "未知主播",
                    stream_url=result.stream_url,
                    room_id=result.room_id,
                    error=result.error,
                )
            return result
        except Exception as exc:
            log.warning("DouyinResolver check_live failed: %s", exc)
        return CheckResult(
            platform="douyin",
            is_live=False,
            live_status=LiveCheckStatus.UNKNOWN.value,
            title="抖音直播",
            streamer="未知主播",
            room_id=room_id,
            error="All resolution strategies failed for this Douyin URL.",
        )

    # ── resolver factory ─────────────────────────────────────

    def _get_resolver(self):
        """Lazy-init the DouyinResolver from config (if available)."""
        if self._resolver is None:
            try:
                from live2note.resolvers import DouyinResolver
                # Try to load per-platform config from AppConfig.
                # Since we don't have AppConfig injected directly,
                # default to the built-in resolver with defaults.
                self._resolver = DouyinResolver()
            except ImportError:
                self._resolver = _NoopResolver()
        return self._resolver

    # ── yt-dlp subprocess (kept for backward compat) ─────────

    @staticmethod
    def _yt_dlp_info(url: str, timeout: int = 30) -> dict:
        cmd = [
            "yt-dlp",
            "--no-download",
            "--no-warnings",
            "-j",
            url,
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError as err:
            raise _YtdlpError("yt-dlp not found. Install it: pip install yt-dlp") from err
        except subprocess.TimeoutExpired as err:
            raise _YtdlpError(f"yt-dlp timed out after {timeout}s") from err

        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise _YtdlpError(stderr or f"exit code {result.returncode}")

        stdout = result.stdout.strip()
        if not stdout:
            raise _YtdlpError("Empty output from yt-dlp")

        first_line = stdout.split("\n")[0]
        try:
            return json.loads(first_line)
        except json.JSONDecodeError as exc:
            raise _YtdlpError(f"Invalid JSON from yt-dlp: {exc}") from exc


class _YtdlpError(Exception):
    """Raised when yt-dlp subprocess fails."""


class _NoopResolver:
    """Sentinel resolver when DouyinResolver is not available."""

    def check_live(self, url: str) -> CheckResult:
        return CheckResult(
            platform="douyin",
            is_live=False,
            live_status=LiveCheckStatus.UNKNOWN.value,
        )

    def resolve_stream_url(self, url: str, stream_url_override: str = "") -> str:
        return stream_url_override or ""
