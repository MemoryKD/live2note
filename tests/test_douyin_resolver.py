"""Tests for DouyinResolver, YtdlpResolver, StreamlinkResolver, ResolveResult, and safe_url.

ALL tests use mocks. No real network calls. No real Douyin URLs in test data.
"""

from __future__ import annotations

from unittest.mock import patch

from live2note.models.resolve_result import (
    ResolveResult,
    ResolveStatus,
    ResolveStrategy,
)
from live2note.models.task import CheckResult, LiveCheckStatus
from live2note.resolvers.douyin_page_resolver import DouyinPageResolver
from live2note.resolvers.douyin_resolver import DouyinResolver
from live2note.resolvers.streamlink_resolver import StreamlinkResolver
from live2note.resolvers.ytdlp_resolver import YtdlpResolver
from live2note.utils.safe_url import safe_url, safe_url_full, safe_url_short

# ── ResolveResult model tests ─────────────────────────────────


class TestResolveResult:
    def test_defaults(self):
        rr = ResolveResult(platform="douyin", source_url="https://live.douyin.com/123")
        assert rr.platform == "douyin"
        assert rr.status == ResolveStatus.ERROR.value
        assert rr.strategy == ResolveStrategy.NONE.value
        assert rr.stream_url == ""
        assert rr.is_live is None
        assert rr.is_resolved is False

    def test_resolved(self):
        rr = ResolveResult(
            platform="douyin",
            source_url="https://live.douyin.com/123",
            status=ResolveStatus.RESOLVED.value,
            strategy=ResolveStrategy.STREAMLINK.value,
            stream_url="https://pull.example.com/stream.flv",
        )
        assert rr.is_resolved is True

    def test_manual_required(self):
        rr = ResolveResult(
            platform="douyin",
            source_url="https://live.douyin.com/123",
            status=ResolveStatus.MANUAL_REQUIRED.value,
            error_message="All strategies failed",
        )
        assert rr.is_resolved is False
        assert rr.status == ResolveStatus.MANUAL_REQUIRED.value

    def test_to_dict_excludes_stream_url(self):
        rr = ResolveResult(
            platform="douyin",
            source_url="https://live.douyin.com/123",
            stream_url="https://pull.example.com/secret123",
        )
        d = rr.to_dict()
        assert "stream_url" not in d
        assert "source_url" in d
        assert "platform" in d

    def test_round_trip(self):
        rr = ResolveResult(
            platform="douyin",
            source_url="https://live.douyin.com/456",
            status=ResolveStatus.RESOLVED.value,
            strategy=ResolveStrategy.STREAMLINK.value,
            title="Test Live",
            streamer="TestStreamer",
            room_id="456",
        )
        d = rr.to_dict()
        restored = ResolveResult.from_dict(d)
        assert restored.platform == rr.platform
        assert restored.status == rr.status
        assert restored.strategy == rr.strategy
        assert restored.title == rr.title

    def test_expires_at_set_correctly(self):
        rr = ResolveResult(
            platform="douyin",
            source_url="https://live.douyin.com/123",
            expires_at="2026-01-01T00:00:00+00:00",
            stream_url_ttl=3600,
        )
        assert rr.stream_url_ttl == 3600
        assert rr.expires_at is not None


# ── safe_url tests ────────────────────────────────────────────


class TestSafeUrl:
    def test_short_url_passthrough(self):
        short = "https://example.com/stream"
        assert safe_url(short) == short

    def test_long_url_truncated(self):
        long = "https://example.com/" + "a" * 100
        result = safe_url(long, max_length=80)
        assert len(result) <= 80
        assert "example.com" in result

    def test_empty_url(self):
        assert safe_url("") == ""

    def test_short_returns_domain_only(self):
        url = "https://pull-q5.douyincdn.com/thirdgame/stream_123_or4.flv?expire=123&sign=abc"
        result = safe_url_short(url)
        assert "pull-q5.douyincdn.com" in result
        assert "expire" not in result
        assert "sign" not in result

    def test_full_returns_complete_url(self):
        url = "https://example.com/stream.flv?token=secret"
        assert safe_url_full(url) == url


# ── YtdlpResolver tests ───────────────────────────────────────


class TestYtdlpResolver:
    def test_resolve_success(self):
        resolver = YtdlpResolver(timeout=10)
        mock_info = {
            "title": "Test Live",
            "uploader": "Streamer",
            "is_live": True,
            "url": "https://pull.example.com/stream.flv",
            "id": "12345",
            "ext": "flv",
        }

        with patch.object(resolver, "_run_ytdlp", return_value=mock_info):
            result = resolver.resolve("https://live.douyin.com/12345")
            assert result.is_resolved
            assert result.strategy == ResolveStrategy.YT_DLP.value
            assert result.title == "Test Live"
            assert "pull.example.com" in result.stream_url

    def test_resolve_not_live(self):
        resolver = YtdlpResolver(timeout=10)
        mock_info = {
            "title": "Offline Stream",
            "is_live": False,
            "url": "",
        }

        with patch.object(resolver, "_run_ytdlp", return_value=mock_info):
            result = resolver.resolve("https://live.douyin.com/12345")
            assert not result.is_resolved

    def test_resolve_ytdlp_error(self):
        resolver = YtdlpResolver(timeout=10)
        from live2note.resolvers.ytdlp_resolver import _YtdlpError

        with patch.object(resolver, "_run_ytdlp", side_effect=_YtdlpError("Unsupported URL")):
            result = resolver.resolve("https://live.douyin.com/12345")
            assert result.status == ResolveStatus.ERROR.value
            assert "Unsupported URL" in result.error_message

    def test_formats_fallback(self):
        """When top-level url is empty, use last format's url."""
        resolver = YtdlpResolver(timeout=10)
        mock_info = {
            "title": "Live",
            "is_live": True,
            "url": "",
            "formats": [
                {"url": "https://cdn.com/low.flv"},
                {"url": "https://cdn.com/high.flv"},
            ],
        }
        with patch.object(resolver, "_run_ytdlp", return_value=mock_info):
            result = resolver.resolve("https://live.douyin.com/12345")
            assert result.is_resolved
            assert "high.flv" in result.stream_url


# ── StreamlinkResolver tests ──────────────────────────────────


class TestStreamlinkResolver:
    def test_resolve_success(self):
        resolver = StreamlinkResolver(quality="best", timeout=10)
        with patch.object(resolver, "_run_streamlink", return_value="https://pull.example.com/stream.flv"):
            result = resolver.resolve("https://live.douyin.com/12345")
            assert result.is_resolved
            assert result.strategy == ResolveStrategy.STREAMLINK.value
            assert result.is_live is True  # streamlink implies live

    def test_resolve_no_streams(self):
        resolver = StreamlinkResolver(quality="best", timeout=10)
        with patch.object(resolver, "_run_streamlink", return_value=""):
            result = resolver.resolve("https://live.douyin.com/12345")
            assert not result.is_resolved

    def test_resolve_streamlink_error(self):
        resolver = StreamlinkResolver(quality="best", timeout=10)
        with patch.object(resolver, "_run_streamlink", side_effect=RuntimeError("No streams found")):
            result = resolver.resolve("https://live.douyin.com/12345")
            assert result.status == ResolveStatus.ERROR.value

    def test_resolve_file_not_found(self):
        resolver = StreamlinkResolver(quality="best", timeout=10)
        with patch.object(resolver, "_run_streamlink", side_effect=FileNotFoundError()):
            result = resolver.resolve("https://live.douyin.com/12345")
            assert "not found" in result.error_message.lower()


# ── DouyinResolver tests ─────────────────────────────────────


class TestDouyinResolver:
    def test_user_override_highest_priority(self):
        dr = DouyinResolver()
        result = dr.resolve(
            "https://live.douyin.com/12345",
            stream_url_override="https://my-stream.example.com/live.flv",
        )
        assert result.is_resolved
        assert result.strategy == ResolveStrategy.USER_OVERRIDE.value
        assert "my-stream" in result.stream_url

    def test_ytdlp_first_then_streamlink(self):
        dr = DouyinResolver({"yt_dlp_enabled": True, "streamlink_enabled": True, "timeout": 5})

        with patch.object(YtdlpResolver, "resolve") as mock_yt, \
             patch.object(StreamlinkResolver, "resolve") as mock_sl:
            # yt-dlp fails
            mock_yt.return_value = ResolveResult(
                platform="douyin", source_url="https://live.douyin.com/12345",
                status="error", strategy="yt_dlp", error_message="fail",
            )
            # streamlink succeeds
            mock_sl.return_value = ResolveResult(
                platform="douyin", source_url="https://live.douyin.com/12345",
                status="resolved", strategy="streamlink",
                stream_url="https://pull.example.com/stream.flv",
            )

            result = dr.resolve("https://live.douyin.com/12345")
            assert result.is_resolved
            assert result.strategy == ResolveStrategy.STREAMLINK.value

    def test_all_strategies_fail(self):
        dr = DouyinResolver({"yt_dlp_enabled": True, "streamlink_enabled": True, "timeout": 5})

        with patch.object(YtdlpResolver, "resolve") as mock_yt, \
             patch.object(StreamlinkResolver, "resolve") as mock_sl, \
             patch.object(DouyinPageResolver, "resolve") as mock_page:
            mock_yt.return_value = ResolveResult(
                platform="douyin", source_url="https://live.douyin.com/12345",
                status="error", error_message="ytdlp failed",
            )
            mock_sl.return_value = ResolveResult(
                platform="douyin", source_url="https://live.douyin.com/12345",
                status="error", error_message="streamlink failed",
            )
            mock_page.return_value = ResolveResult(
                platform="douyin", source_url="https://live.douyin.com/12345",
                status="error", error_message="page parse failed",
            )

            result = dr.resolve("https://live.douyin.com/12345")
            assert result.status == ResolveStatus.MANUAL_REQUIRED.value
            assert not result.is_resolved

    def test_disabled_strategies_skipped(self):
        dr = DouyinResolver({"yt_dlp_enabled": False, "streamlink_enabled": False, "timeout": 5})

        result = dr.resolve("https://live.douyin.com/12345")
        assert result.status == ResolveStatus.MANUAL_REQUIRED.value

    def test_check_live_via_ytdlp(self):
        dr = DouyinResolver({"yt_dlp_enabled": True, "streamlink_enabled": False, "timeout": 5})

        with patch.object(YtdlpResolver, "resolve") as mock_yt:
            mock_yt.return_value = ResolveResult(
                platform="douyin", source_url="https://live.douyin.com/12345",
                status="resolved", strategy="yt_dlp",
                is_live=True, title="Live Now", streamer="Host",
                stream_url="https://pull.example.com/stream.flv",
            )
            result = dr.check_live("https://live.douyin.com/12345")
            assert isinstance(result, CheckResult)
            assert result.is_live is True
            assert result.title == "Live Now"

    def test_check_live_fallback_to_streamlink(self):
        dr = DouyinResolver({"yt_dlp_enabled": True, "streamlink_enabled": True, "timeout": 5})

        with patch.object(YtdlpResolver, "resolve") as mock_yt, \
             patch.object(StreamlinkResolver, "resolve") as mock_sl:
            mock_yt.side_effect = RuntimeError("yt-dlp crash")
            mock_sl.return_value = ResolveResult(
                platform="douyin", source_url="https://live.douyin.com/12345",
                status="resolved", strategy="streamlink",
                stream_url="https://pull.example.com/stream.flv",
            )
            result = dr.check_live("https://live.douyin.com/12345")
            assert result.is_live is True
            assert result.live_status == LiveCheckStatus.LIVE.value

    def test_resolve_stream_url_convenience(self):
        dr = DouyinResolver({"yt_dlp_enabled": False, "streamlink_enabled": True, "timeout": 5})

        with patch.object(StreamlinkResolver, "resolve") as mock_sl:
            mock_sl.return_value = ResolveResult(
                platform="douyin", source_url="https://live.douyin.com/12345",
                status="resolved", strategy="streamlink",
                stream_url="https://pull.example.com/stream.flv",
            )
            url = dr.resolve_stream_url("https://live.douyin.com/12345")
            assert url == "https://pull.example.com/stream.flv"

    def test_debug_mode_accumulates_info(self):
        dr = DouyinResolver({"yt_dlp_enabled": True, "streamlink_enabled": False, "timeout": 5})

        with patch.object(YtdlpResolver, "resolve") as mock_yt:
            mock_yt.return_value = ResolveResult(
                platform="douyin", source_url="https://live.douyin.com/12345",
                status="error", error_message="blocked",
                debug_info={"timing": 2.5},
            )
            result = dr.resolve("https://live.douyin.com/12345", debug=True)
            assert result.debug_info != {}

    def test_page_resolver_fallback_after_streamlink(self):
        """When yt-dlp and streamlink fail, page resolver should be tried next."""
        dr = DouyinResolver({"yt_dlp_enabled": True, "streamlink_enabled": True, "timeout": 5})

        with patch.object(YtdlpResolver, "resolve") as mock_yt, \
             patch.object(StreamlinkResolver, "resolve") as mock_sl, \
             patch.object(DouyinPageResolver, "resolve") as mock_page:
            mock_yt.return_value = ResolveResult(
                platform="douyin", source_url="https://v.douyin.com/test",
                status="error", error_message="unsupported",
            )
            mock_sl.return_value = ResolveResult(
                platform="douyin", source_url="https://v.douyin.com/test",
                status="error", error_message="no streams",
            )
            mock_page.return_value = ResolveResult(
                platform="douyin", source_url="https://v.douyin.com/test",
                status="resolved", strategy="page_public_data",
                stream_url="https://pull-flv.douyincdn.com/stream_or4.flv",
                room_id="7636344970135341862",
            )

            result = dr.resolve("https://v.douyin.com/test")
            assert result.is_resolved
            assert result.strategy == ResolveStrategy.PAGE_PUBLIC_DATA.value
            assert "douyincdn.com" in result.stream_url
            assert result.room_id == "7636344970135341862"


# ── DouyinPageResolver tests ─────────────────────────────────


class TestDouyinPageResolver:
    def test_is_short_link(self):
        assert DouyinPageResolver.is_short_link("https://v.douyin.com/PplPeCxihTA/") is True
        assert DouyinPageResolver.is_short_link("https://live.douyin.com/12345") is False

    def test_is_reflow_page(self):
        assert DouyinPageResolver.is_reflow_page(
            "https://webcast.amemv.com/douyin/webcast/reflow/7636344970135341862"
        ) is True
        assert DouyinPageResolver.is_reflow_page("https://live.douyin.com/12345") is False

    def test_extract_flv_urls(self):
        html = '''
        <script>self.__pace_f.push([1,"aa:bb"])</script>
        <script>var a="https://pull-flv-l26.douyincdn.com/stage/stream_123_or4.flv?expire=abc\\u0026sign=xyz\\u0026neq=1"</script>
        <script>var b="https://pull-flv-l26.douyincdn.com/stage/stream_123.flv?expire=abc\\u0026sign=xyz\\u0026only_audio=1"</script>
        '''
        urls = DouyinPageResolver._extract_flv_urls(html)
        assert len(urls) == 2
        assert "douyincdn.com" in urls[0]
        assert "&sign=xyz" in urls[0]  # \\u0026 was converted to &
        assert "&only_audio=1" in urls[1]

    def test_pick_best_flv_prefers_or4(self):
        urls = [
            "https://cdn.com/stream.flv?only_audio=1&sign=x",
            "https://cdn.com/stream_or4.flv?sign=y",
            "https://cdn.com/stream_Stage0T000hd.flv?sign=z",
        ]
        best = DouyinPageResolver._pick_best_flv(urls)
        assert "_or4" in best

    def test_pick_best_flv_fallback_to_hd(self):
        urls = [
            "https://cdn.com/stream.flv?only_audio=1&sign=x",
            "https://cdn.com/stream_Stage0T000hd.flv?sign=z",
        ]
        best = DouyinPageResolver._pick_best_flv(urls)
        assert "_Stage0T000hd" in best

    def test_pick_best_flv_skips_audio_only(self):
        urls = [
            "https://cdn.com/stream.flv?only_audio=1&sign=x",
            "https://cdn.com/stream.flv?sign=y",
        ]
        best = DouyinPageResolver._pick_best_flv(urls)
        assert "only_audio" not in best

    def test_resolve_via_mock_page(self):
        """Mock the HTTP session to return a simulated reflow page."""
        resolver = DouyinPageResolver(timeout=5)

        mock_html = '''
        <script>
        var urls = {
            flv: "https://pull-flv-l26.douyincdn.com/stage/stream_119_or4.flv?expire=abc\\u0026sign=xyz\\u0026neq=1"
        };
        </script>
        '''

        class MockResponse:
            url = "https://webcast.amemv.com/douyin/webcast/reflow/7636344970135341862?params=..."
            text = mock_html

            def __init__(self, *args, **kwargs):
                pass

        with patch.object(resolver, "_get_session") as mock_session_fn:
            mock_session = mock_session_fn.return_value
            mock_session.get.return_value = MockResponse()

            result = resolver.resolve("https://v.douyin.com/PplPeCxihTA/")
            assert result.is_resolved
            assert result.strategy == ResolveStrategy.PAGE_PUBLIC_DATA.value
            assert result.room_id == "7636344970135341862"
            assert "douyincdn.com" in result.stream_url
            assert "stream_119_or4" in result.stream_url

    def test_resolve_no_flv_in_page(self):
        resolver = DouyinPageResolver(timeout=5)

        class MockResponse:
            url = "https://webcast.amemv.com/douyin/webcast/reflow/123"
            text = "<html><body>no streams here</body></html>"

        with patch.object(resolver, "_get_session") as mock_session_fn:
            mock_session_fn.return_value.get.return_value = MockResponse()
            result = resolver.resolve("https://v.douyin.com/test")
            assert not result.is_resolved
            assert result.status == ResolveStatus.ERROR.value

    def test_douyinliving_domain_flv(self):
        """FLV from douyinliving.com domain should be extracted."""
        html = '<script>var a="https://pull-f5.douyinliving.com/thirdgame/stream-119.flv?expire=abc\\u0026sign=xyz"</script>'
        urls = DouyinPageResolver._extract_flv_urls(html)
        assert len(urls) == 1
        assert "douyinliving.com" in urls[0]
        assert "&sign=xyz" in urls[0]

    def test_playwright_disabled_by_default_in_test(self):
        """When playwright_enabled=False, anti-bot shells just fail."""
        resolver = DouyinPageResolver(timeout=5, playwright_enabled=False)

        class MockResponse:
            url = "https://live.douyin.com/12345"
            text = "<html><head></head><body></body></html>"  # 49 bytes — anti-bot shell

        with patch.object(resolver, "_get_session") as mock_session_fn:
            mock_session_fn.return_value.get.return_value = MockResponse()
            result = resolver.resolve("https://live.douyin.com/12345")
            assert not result.is_resolved  # Playwright not enabled, fails

    def test_anti_bot_detection_triggered(self):
        """Small page (<10KB) without __pace_f should trigger Playwright check."""
        resolver = DouyinPageResolver(timeout=5, playwright_enabled=True)
        assert resolver._should_try_playwright("<html></html>")  # tiny shell
        assert resolver._should_try_playwright("a" * 5000)  # below threshold, no stream data

    def test_normal_page_no_playwright(self):
        """Large pages or pages with __pace_f should NOT trigger Playwright."""
        resolver = DouyinPageResolver(timeout=5, playwright_enabled=True)
        large = "a" * 15000  # above threshold
        assert not resolver._should_try_playwright(large)
