"""Douyin multi-level stream URL resolution orchestrator.

Resolution order:
  1. --stream-url override (user provides directly)
  2. yt-dlp (if enabled in config)
  3. streamlink (if enabled in config)
  4. page public data (v.douyin.com → webcast reflow → FLV extraction)
  5. manual_required (user must provide stream URL)

Never reads browser cookies automatically.
Never bypasses platform access controls.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from live2note.logger import get_logger
from live2note.models.resolve_result import (
    ResolveResult,
    ResolveStatus,
    ResolveStrategy,
)
from live2note.models.task import CheckResult, LiveCheckStatus
from live2note.resolvers.douyin_page_resolver import DouyinPageResolver
from live2note.resolvers.streamlink_resolver import StreamlinkResolver
from live2note.resolvers.ytdlp_resolver import YtdlpResolver
from live2note.utils.safe_url import safe_url

log = get_logger("resolver.douyin")

# Default resolution config — can be overridden from config.yaml platforms.douyin.resolver
_DEFAULT_RESOLVER_CONFIG = {
    "timeout": 30,
    "cookie_file": "",
    "streamlink_enabled": True,
    "yt_dlp_enabled": True,
    "stream_url_ttl": 3600,
    "quality": "best",
}


class DouyinResolver:
    """Multi-level resolver for Douyin live stream URLs.

    Attempts resolution in priority order. All strategies fail soft —
    the caller always gets a ResolveResult, never an exception.
    """

    def __init__(self, resolver_config: dict | None = None) -> None:
        cfg = {**_DEFAULT_RESOLVER_CONFIG, **(resolver_config or {})}
        self._timeout = int(cfg.get("timeout", 30))
        self._cookie_file = str(cfg.get("cookie_file", ""))
        self._streamlink_enabled = bool(cfg.get("streamlink_enabled", True))
        self._yt_dlp_enabled = bool(cfg.get("yt_dlp_enabled", True))
        self._stream_url_ttl = int(cfg.get("stream_url_ttl", 3600))
        self._quality = str(cfg.get("quality", "best"))

    @property
    def cookie_file(self) -> str:
        return self._cookie_file

    # ── public API ──────────────────────────────────────────

    def resolve(
        self,
        url: str,
        stream_url_override: str = "",
        debug: bool = False,
    ) -> ResolveResult:
        """Resolve a Douyin live stream URL to a recordable stream URL.

        Args:
            url:                  The original Douyin room URL.
            stream_url_override:  User-provided --stream-url value (highest priority).
            debug:                If True, include per-step diagnostics.

        Returns:
            ResolveResult — check ``.is_resolved`` or ``.status``.
        """
        # Tier 1: User override.
        if stream_url_override:
            log.info("Douyin resolve: using --stream-url override")
            return self._make_result(
                status=ResolveStatus.RESOLVED.value,
                strategy=ResolveStrategy.USER_OVERRIDE.value,
                stream_url=stream_url_override,
                debug_info=_debug_ctx(debug, "override", "user-provided --stream-url"),
            )

        debug_entries: list[dict[str, object]] = []

        # Tier 2: yt-dlp.
        if self._yt_dlp_enabled:
            log.info("Douyin resolve: trying yt-dlp")
            yt = YtdlpResolver(
                ytdlp_path="yt-dlp",
                timeout=self._timeout,
                cookie_file=self._cookie_file,
            )
            result = yt.resolve(url, debug=debug)
            if result.is_resolved:
                return self._enrich(result, url, debug_entries if debug else {})
            debug_entries.append({"strategy": "yt_dlp", "status": result.status, "error": result.error_message})

        # Tier 3: streamlink.
        if self._streamlink_enabled:
            log.info("Douyin resolve: trying streamlink")
            sl = StreamlinkResolver(
                quality=self._quality,
                timeout=self._timeout,
                cookie_file=self._cookie_file,
            )
            result = sl.resolve(url, debug=debug)
            if result.is_resolved:
                return self._enrich(result, url, debug_entries if debug else {})
            debug_entries.append({"strategy": "streamlink", "status": result.status, "error": result.error_message})

        # Tier 4: Page public data (v.douyin.com short-link redirect + embedded FLV extraction).
        log.info("Douyin resolve: trying page public data")
        try:
            page = DouyinPageResolver(timeout=self._timeout)
            try:
                result = page.resolve(url, debug=debug)
                if result.is_resolved:
                    return self._enrich(result, url, debug_entries if debug else {})
                debug_entries.append({"strategy": "page_public_data", "status": result.status, "error": result.error_message})
            finally:
                page.close()
        except Exception:
            debug_entries.append({"strategy": "page_public_data", "status": "error", "error": "exception"})

        # Tier 5: Manual required.
        log.warning("Douyin resolve: all strategies failed — manual stream_url required")
        return self._make_result(
            status=ResolveStatus.MANUAL_REQUIRED.value,
            strategy=ResolveStrategy.NONE.value,
            error_message=(
                "All automatic resolution strategies failed for Douyin.\n"
                "You can:\n"
                "  1. Provide a direct stream URL with --stream-url.\n"
                "  2. Use --platform generic with a known m3u8/flv URL.\n"
                "  3. Check if the stream requires login or special access.\n"
                "  4. Install streamlink: pip install streamlink\n"
                "  5. Use 'live2note resolve <url> --debug-resolve' for details."
            ),
            debug_info={"_attempts": debug_entries} if debug else {},
        )

    def check_live(self, url: str) -> CheckResult:
        """Check if a Douyin stream is currently live.

        Tries yt-dlp first, then streamlink, then page data.
        Always returns safe default metadata (never empty title/author).
        """
        author = ""
        title = ""
        stream_url = ""
        room_id = ""

        # Try yt-dlp first (richest metadata).
        if self._yt_dlp_enabled:
            try:
                yt = YtdlpResolver(timeout=self._timeout, cookie_file=self._cookie_file)
                resolve_result = yt.resolve(url)
                if resolve_result.is_resolved:
                    author = resolve_result.streamer
                    title = resolve_result.title
                    stream_url = resolve_result.stream_url
                    room_id = resolve_result.room_id
                    return self._make_check_result(
                        url=url, is_live=resolve_result.is_live or False,
                        live_status=LiveCheckStatus.LIVE.value if resolve_result.is_live else LiveCheckStatus.NOT_LIVE.value,
                        stream_url=stream_url, title=title, author=author,
                        room_id=room_id, error=resolve_result.error_message or None,
                    )
                author = author or resolve_result.streamer
                title = title or resolve_result.title
                room_id = room_id or resolve_result.room_id
            except Exception:
                pass

        # Fallback: streamlink (tells us if stream is live, no rich metadata).
        if self._streamlink_enabled:
            try:
                sl = StreamlinkResolver(quality=self._quality, timeout=self._timeout, cookie_file=self._cookie_file)
                resolve_result = sl.resolve(url)
                if resolve_result.is_resolved:
                    stream_url = stream_url or resolve_result.stream_url
                    return self._make_check_result(
                        url=url, is_live=True, live_status=LiveCheckStatus.LIVE.value,
                        stream_url=resolve_result.stream_url,
                        title=title, author=author, room_id=room_id,
                    )
            except Exception:
                pass

        # Try page public data as a last check.
        try:
            page = DouyinPageResolver(timeout=self._timeout)
            try:
                resolve_result = page.resolve(url)
                if resolve_result.is_resolved:
                    stream_url = stream_url or resolve_result.stream_url
                    room_id = room_id or resolve_result.room_id
                    return self._make_check_result(
                        url=url, is_live=True, live_status=LiveCheckStatus.LIVE.value,
                        stream_url=stream_url, title=title, author=author,
                        room_id=room_id,
                    )
            finally:
                page.close()
        except Exception:
            pass

        return self._make_check_result(
            url=url, is_live=False, live_status=LiveCheckStatus.UNKNOWN.value,
            stream_url=stream_url, title=title, author=author,
            room_id=room_id,
            error="Could not determine live status.",
        )

    def _make_check_result(self, url: str, is_live: bool, live_status: str,
                           stream_url: str, title: str, author: str,
                           room_id: str, error: str | None = None) -> CheckResult:
        """Build a CheckResult with safe default metadata."""
        title = title or "抖音直播"
        author = author or "未知主播"
        return CheckResult(
            platform="douyin",
            is_live=is_live,
            live_status=live_status,
            title=title,
            streamer=author,
            stream_url=stream_url,
            room_id=room_id,
            error=error,
        )

    def resolve_stream_url(self, url: str, stream_url_override: str = "") -> str:
        """Convenience: resolve and return the stream_url string or empty string."""
        result = self.resolve(url, stream_url_override=stream_url_override)
        log.info(
            "Douyin resolve: status=%s strategy=%s stream_url=%s",
            result.status, result.strategy, safe_url(result.stream_url),
        )
        return result.stream_url

    # ── helpers ─────────────────────────────────────────────

    def _make_result(self, **kwargs: object) -> ResolveResult:
        """Create a ResolveResult with defaults filled in."""
        defaults: dict[str, object] = {
            "platform": "douyin",
            "source_url": "",
            "expires_at": _compute_expiry(self._stream_url_ttl),
            "stream_url_ttl": self._stream_url_ttl,
        }
        defaults.update(kwargs)
        return ResolveResult(**{k: v for k, v in defaults.items() if k in ResolveResult.__dataclass_fields__})

    def _enrich(self, result: ResolveResult, source_url: str, debug_info: dict | list) -> ResolveResult:
        """Add source_url, expiry, and debug info to a resolver result."""
        enriched = {
            **{k: getattr(result, k) for k in ResolveResult.__dataclass_fields__},
            "source_url": source_url,
            "expires_at": _compute_expiry(self._stream_url_ttl),
            "stream_url_ttl": self._stream_url_ttl,
        }
        if debug_info:
            enriched["debug_info"] = (
                {"_chain": debug_info} if isinstance(debug_info, list) else debug_info
            )
        return ResolveResult(**enriched)


def _compute_expiry(ttl_seconds: int) -> str | None:
    """Compute an ISO expiry timestamp from now + ttl_seconds."""
    if ttl_seconds <= 0:
        return None
    return (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()


def _debug_ctx(debug: bool, strategy: str, detail: str) -> dict[str, object]:
    if not debug:
        return {}
    return {strategy: {"detail": detail}}
