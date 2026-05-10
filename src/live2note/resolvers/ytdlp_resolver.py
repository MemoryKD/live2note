"""yt-dlp based stream URL resolver.

Extracted from DouyinAdapter._yt_dlp_info so it can be shared across adapters.
"""

from __future__ import annotations

import json
import subprocess

from live2note.logger import get_logger
from live2note.models.resolve_result import (
    ResolveResult,
    ResolveStatus,
    ResolveStrategy,
)
from live2note.utils.safe_url import safe_url

log = get_logger("resolver.ytdlp")


class _YtdlpError(Exception):
    """Raised when yt-dlp subprocess fails."""


class YtdlpResolver:
    """Resolve stream URL and metadata using yt-dlp.

    Usage:
        resolver = YtdlpResolver(timeout=30)
        result = resolver.resolve("https://live.douyin.com/12345")
        if result.is_resolved:
            print(result.stream_url)
    """

    def __init__(
        self,
        ytdlp_path: str = "yt-dlp",
        timeout: int = 30,
        cookie_file: str = "",
    ) -> None:
        self._ytdlp = ytdlp_path
        self._timeout = timeout
        self._cookie_file = cookie_file

    def resolve(self, url: str, debug: bool = False) -> ResolveResult:
        """Attempt to resolve a stream URL via yt-dlp -j.

        Returns ResolveResult with strategy="yt_dlp".
        """
        debug_info: dict[str, object] = {}
        try:
            info = self._run_ytdlp(url)
            stream_url = info.get("url", "")
            if not stream_url and info.get("formats"):
                best = info["formats"][-1]
                stream_url = best.get("url", "")
            return ResolveResult(
                platform="douyin",
                source_url=url,
                status=ResolveStatus.RESOLVED.value if stream_url else ResolveStatus.ERROR.value,
                strategy=ResolveStrategy.YT_DLP.value,
                stream_url=stream_url,
                is_live=info.get("is_live", False) or info.get("live_status") == 1,
                title=info.get("title", ""),
                streamer=info.get("uploader", info.get("creator", "")),
                room_id=info.get("id", ""),
                stream_format=info.get("ext", ""),
                debug_info=debug_info if debug else {},
            )
        except _YtdlpError as exc:
            log.info("yt-dlp failed for %s: %s", safe_url(url), exc)
            return ResolveResult(
                platform="douyin",
                source_url=url,
                status=ResolveStatus.ERROR.value,
                strategy=ResolveStrategy.YT_DLP.value,
                error_message=str(exc),
                debug_info=debug_info if debug else {},
            )

    def check_live(self, url: str) -> ResolveResult:
        """Lightweight liveness check via yt-dlp."""
        return self.resolve(url)

    def _run_ytdlp(self, url: str) -> dict:
        """Run yt-dlp -j and return parsed JSON. Raises _YtdlpError on failure."""
        cmd = [self._ytdlp, "--no-download", "--no-warnings", "-j"]
        if self._cookie_file:
            cmd.extend(["--cookies", self._cookie_file])
        cmd.append(url)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError as err:
            raise _YtdlpError("yt-dlp not found. Install it: pip install yt-dlp") from err
        except subprocess.TimeoutExpired as err:
            raise _YtdlpError(f"yt-dlp timed out after {self._timeout}s") from err

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
