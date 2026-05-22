"""Douyin page-based stream URL resolver.

Handles ``v.douyin.com`` short links and ``webcast.amemv.com/reflow/`` pages.
Follows redirects and extracts embedded FLV/HLS stream URLs from page scripts.

For rooms with strong anti-bot protection, falls back to Playwright headed
browser mode to capture stream URLs from network traffic.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone

from live2note.logger import get_logger
from live2note.models.resolve_result import (
    ResolveResult,
    ResolveStatus,
    ResolveStrategy,
)
from live2note.utils.safe_url import safe_url

log = get_logger("resolver.douyin_page")

# Douyin short link domain
_V_DOUYIN_RE = re.compile(r"v\.douyin\.com/([a-zA-Z0-9]+)")

# Webcast reflow page — redirect target for v.douyin.com live links
_REFLOW_RE = re.compile(r"webcast\.amemv\.com/douyin/webcast/reflow/(\d+)")

# Page size threshold: anything below is considered an anti-bot shell
_ANTI_BOT_THRESHOLD = 10000

# FLV URL patterns — matches both douyincdn.com and douyinliving.com domains
_FLV_URL_RE = re.compile(
    r"(https?://(?:pull-flv|pull-f\d+)"
    r"[^\"\s<>]+"
    r"\.(?:flv|m3u8)\?"
    r"[^\"\s<>]+)"
)


class DouyinPageResolver:
    """Extract stream URLs from Douyin page data via HTTP and Playwright.

    Resolution strategy:
      1. HTTP request → follow redirects → extract FLV from page scripts
      2. If page is anti-bot shell (< 10KB) → fall back to Playwright browser

    Playwright is optional — if not installed, only HTTP is used.
    """

    def __init__(self, timeout: int = 15, playwright_enabled: bool = True) -> None:
        self._timeout = timeout
        self._session = None  # type: ignore[assignment]
        self._playwright_enabled = playwright_enabled

    def close(self) -> None:
        """Close the underlying HTTP session if created."""
        if self._session is not None:
            self._session.close()
            self._session = None  # type: ignore[assignment]

    def resolve(self, url: str, debug: bool = False) -> ResolveResult:
        """Resolve a Douyin URL to a recordable stream URL.

        Returns ResolveResult with strategy="page_public_data".
        """
        debug_info: dict[str, object] = {}
        t0 = datetime.now(timezone.utc)

        # ── Tier 1: HTTP page extraction ──
        try:
            session = self._get_session()
            resp = session.get(url, allow_redirects=True, timeout=self._timeout)
            final_url = resp.url
            page_text = resp.text
            elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
            debug_info["redirect_to"] = final_url
            debug_info["page_bytes"] = len(page_text)
            debug_info["elapsed_s"] = round(elapsed, 1)

            room_id = self._extract_room_id(final_url)
            flv_urls = self._extract_flv_urls(page_text)
            debug_info["flv_urls_found"] = len(flv_urls)
            debug_info["method"] = "http"

            if flv_urls:
                return self._success(url, self._pick_best_flv(flv_urls),
                                     room_id, debug_info if debug else {})

            # ── Tier 2: Playwright browser fallback ──
            if self._should_try_playwright(page_text):
                log.info("Anti-bot shell detected (%d bytes), trying Playwright", len(page_text))
                pw_result = self._resolve_via_playwright(url, room_id, debug_info if debug else {})
                if pw_result and pw_result.is_resolved:
                    return pw_result

            return ResolveResult(
                platform="douyin",
                source_url=url,
                status=ResolveStatus.ERROR.value,
                strategy=ResolveStrategy.PAGE_PUBLIC_DATA.value,
                room_id=room_id,
                error_message="No FLV stream URLs found in page data.",
                debug_info=debug_info if debug else {},
            )

        except Exception as exc:
            log.info("Page resolution failed for %s: %s", safe_url(url), exc)
            return ResolveResult(
                platform="douyin",
                source_url=url,
                status=ResolveStatus.ERROR.value,
                strategy=ResolveStrategy.PAGE_PUBLIC_DATA.value,
                error_message=str(exc),
                debug_info=debug_info if debug else {},
            )

    # ── Playwright browser resolution ─────────────────────────

    def _should_try_playwright(self, page_text: str) -> bool:
        """Return True if the page looks like an anti-bot shell."""
        if not self._playwright_enabled:
            return False
        if len(page_text) >= _ANTI_BOT_THRESHOLD:
            return False
        if "__pace_f" not in page_text and "stream" not in page_text.lower():
            return True
        return False

    def _resolve_via_playwright(
        self, url: str, room_id: str, debug_info: dict[str, object]
    ) -> ResolveResult | None:
        """Launch headed Chromium, capture stream URLs from network traffic."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            log.info("Playwright not installed — skipping browser fallback")
            return None

        t0 = time.monotonic()
        stream_urls: list[str] = []

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=False,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1920, "height": 1080},
                )
                page = context.new_page()
                page.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', "
                    "{get: () => undefined})"
                )

                # Capture stream URLs from network responses
                def on_response(response):
                    resp_url = response.url
                    if any(k in resp_url for k in [
                        "pull-flv", "pull-f", "douyincdn.com/",
                        "douyinliving.com/",
                    ]) and any(resp_url.endswith(ext) for ext in [".flv", ".m3u8"]):
                        stream_urls.append(resp_url)

                page.on("response", on_response)

                log.info("Playwright: loading %s", safe_url(url))
                page.goto(url, wait_until="networkidle", timeout=30000)
                time.sleep(5)  # wait for video player to initialize

                # Also extract from page content
                content = page.content()
                page_flv = self._extract_flv_urls(content)
                for u in page_flv:
                    if u not in stream_urls:
                        stream_urls.append(u)

                browser.close()

        except Exception as exc:
            log.warning("Playwright resolution failed: %s", exc)
            return None

        elapsed = time.monotonic() - t0
        debug_info["playwright_elapsed_s"] = round(elapsed, 1)
        debug_info["playwright_streams"] = len(stream_urls)
        debug_info["method"] = "playwright"

        if not stream_urls:
            return ResolveResult(
                platform="douyin",
                source_url=url,
                status=ResolveStatus.ERROR.value,
                strategy=ResolveStrategy.PAGE_PUBLIC_DATA.value,
                room_id=room_id,
                error_message="Playwright found no stream URLs.",
                debug_info=debug_info,
            )

        best_url = self._pick_best_flv(stream_urls)
        return self._success(url, best_url, room_id, debug_info)

    # ── internal helpers ─────────────────────────────────────

    def _get_session(self):
        import requests  # lazy import — not needed for Playwright-only use

        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
            })
        return self._session

    @staticmethod
    def _extract_room_id(url: str) -> str:
        m = _REFLOW_RE.search(url)
        if m:
            return m.group(1)
        m2 = re.search(r"live\.douyin\.com/(\d+)", url)
        if m2:
            return m2.group(1)
        return ""

    @staticmethod
    def _extract_flv_urls(page_text: str) -> list[str]:
        """Extract all FLV/HLS stream URLs from page content."""
        raw_urls = _FLV_URL_RE.findall(page_text)
        return [u.replace("\\u0026", "&") for u in raw_urls]

    @staticmethod
    def _pick_best_flv(urls: list[str]) -> str:
        """Select the best quality FLV URL.

        Prefers: _or4 (original quality) > HD > any flv.
        Skips: audio-only streams (only_audio=1), admin/md variants.
        """
        or4 = [u for u in urls if "_or4" in u and "only_audio=1" not in u]
        if or4:
            return or4[0]
        hd = [u for u in urls if "hd" in u.lower() and "only_audio=1" not in u]
        if hd:
            return hd[0]
        standard = [u for u in urls
                    if "only_audio=1" not in u
                    and "_admin" not in u
                    and "_md." not in u]
        if standard:
            return standard[0]
        return urls[0] if urls else ""

    @staticmethod
    def _success(url: str, stream_url: str, room_id: str,
                 debug_info: dict[str, object]) -> ResolveResult:
        return ResolveResult(
            platform="douyin",
            source_url=url,
            status=ResolveStatus.RESOLVED.value,
            strategy=ResolveStrategy.PAGE_PUBLIC_DATA.value,
            stream_url=stream_url,
            is_live=True,
            room_id=room_id,
            stream_format="flv",
            debug_info=debug_info,
        )

    @staticmethod
    def is_short_link(url: str) -> bool:
        """Return True if *url* is a v.douyin.com short link."""
        return bool(_V_DOUYIN_RE.search(url))

    @staticmethod
    def is_reflow_page(url: str) -> bool:
        """Return True if *url* is a webcast reflow page."""
        return bool(_REFLOW_RE.search(url))
