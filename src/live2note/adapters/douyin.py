"""Douyin live adapter — uses yt-dlp for public metadata extraction."""

from __future__ import annotations

import json
import re
import subprocess

from live2note.adapters.base import BaseAdapter
from live2note.logger import get_logger
from live2note.models.task import CheckResult

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

    Uses yt-dlp for public metadata. If yt-dlp cannot parse the page
    (e.g. due to anti-bot JS), returns a clear error suggesting
    --platform generic with a direct stream URL.
    """

    def match(self, url: str) -> bool:
        return bool(_DOUYIN_LIVE_RE.search(url) or _DOUYIN_ROOM_RE.search(url))

    def get_platform(self) -> str:
        return "douyin"

    def check_live(self, url: str) -> CheckResult:
        m = _DOUYIN_LIVE_RE.search(url)
        if m:
            room_id = m.group(1)
            canonical = f"https://live.douyin.com/{room_id}"
        else:
            m2 = _DOUYIN_ROOM_RE.search(url)
            if m2:
                room_id = m2.group(1)
                canonical = url
            else:
                return CheckResult(
                    platform="douyin",
                    is_live=False,
                    error="Cannot parse Douyin room ID from URL.",
                )

        try:
            info = self._yt_dlp_info(canonical)
        except _YtdlpError as exc:
            log.warning("yt-dlp failed for %s: %s", canonical, exc)
            return CheckResult(
                platform="douyin",
                is_live=False,
                room_id=room_id,
                error=(
                    f"yt-dlp error: {exc}\n"
                    "Douyin may require browser JS. Try:\n"
                    "  1. Open the live room in your browser.\n"
                    "  2. Copy the direct .flv/.m3u8 stream URL from DevTools.\n"
                    "  3. Use: live2note run <stream_url> --platform generic"
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

        log.info(
            "Douyin room %s: live=%s, title=%s",
            room_id,
            is_live,
            title[:60] if title else "(empty)",
        )

        return CheckResult(
            platform="douyin",
            is_live=is_live,
            title=title,
            streamer=streamer,
            stream_url=stream_url,
            room_id=room_id,
            cover_url=thumbnail,
            error=None if is_live else "Stream is not currently live.",
        )

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
