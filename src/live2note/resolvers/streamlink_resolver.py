"""streamlink-based stream URL resolver for Douyin and other live platforms."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone

from live2note.logger import get_logger
from live2note.models.resolve_result import (
    ResolveResult,
    ResolveStatus,
    ResolveStrategy,
)
from live2note.utils.safe_url import safe_url

log = get_logger("resolver.streamlink")


class StreamlinkResolver:
    """Resolve stream URL using streamlink (Python subprocess wrapper).

    Usage:
        resolver = StreamlinkResolver(quality="best", timeout=30)
        result = resolver.resolve("https://live.douyin.com/12345")
        if result.is_resolved:
            print(result.stream_url)
    """

    def __init__(
        self,
        quality: str = "best",
        timeout: int = 30,
        cookie_file: str = "",
    ) -> None:
        self._quality = quality
        self._timeout = timeout
        self._cookie_file = cookie_file

    def resolve(self, url: str, debug: bool = False) -> ResolveResult:
        """Attempt to resolve a stream URL via streamlink.

        Returns ResolveResult with strategy="streamlink".
        """
        debug_info: dict[str, object] = {}
        t0 = datetime.now(timezone.utc)
        try:
            stream_url = self._run_streamlink(url)
            elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
            debug_info["elapsed_seconds"] = round(elapsed, 1)
            return ResolveResult(
                platform="douyin",
                source_url=url,
                status=ResolveStatus.RESOLVED.value if stream_url else ResolveStatus.ERROR.value,
                strategy=ResolveStrategy.STREAMLINK.value,
                stream_url=stream_url,
                is_live=True if stream_url else None,
                stream_format="flv",
                debug_info=debug_info if debug else {},
            )
        except FileNotFoundError:
            return ResolveResult(
                platform="douyin",
                source_url=url,
                status=ResolveStatus.ERROR.value,
                strategy=ResolveStrategy.STREAMLINK.value,
                error_message="streamlink not found. Install it: pip install streamlink",
                debug_info=debug_info if debug else {},
            )
        except Exception as exc:
            log.info("streamlink failed for %s: %s", safe_url(url), exc)
            return ResolveResult(
                platform="douyin",
                source_url=url,
                status=ResolveStatus.ERROR.value,
                strategy=ResolveStrategy.STREAMLINK.value,
                error_message=str(exc),
                debug_info=debug_info if debug else {},
            )

    def _run_streamlink(self, url: str) -> str:
        """Run streamlink and return the resolved stream URL."""
        cmd = [
            "python", "-m", "streamlink",
            url,
            self._quality,
            "--stream-url",
        ]
        if self._cookie_file:
            cmd.extend(["--http-cookies", self._cookie_file])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self._timeout,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "No playable streams" in stderr:
                return ""
            raise RuntimeError(stderr or f"streamlink exit code {result.returncode}")

        return result.stdout.strip()
