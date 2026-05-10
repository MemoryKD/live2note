"""Tests for platform adapters and registry."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from live2note.adapters.bilibili import BilibiliAdapter
from live2note.adapters.douyin import DouyinAdapter
from live2note.adapters.generic import GenericStreamAdapter, is_stream_url
from live2note.adapters.registry import (
    get_adapter,
    get_adapter_by_name,
    get_adapter_or_raise,
    list_adapters,
)

# ── GenericStreamAdapter / is_stream_url ────────────────────


class TestIsStreamUrl:
    def test_m3u8(self):
        assert is_stream_url("https://example.com/live.m3u8")

    def test_m3u8_with_query(self):
        assert is_stream_url("https://example.com/live/index.m3u8?token=abc")

    def test_flv(self):
        assert is_stream_url("https://example.com/stream.flv")

    def test_rtmp(self):
        assert is_stream_url("rtmp://live.example.com/stream/key")

    def test_rtmps(self):
        assert is_stream_url("rtmps://live.example.com/stream/key")

    def test_http_with_hints(self):
        assert is_stream_url("https://example.com/live/pull/stream")

    def test_html_page_not_stream(self):
        assert not is_stream_url("https://example.com/page.html")

    def test_bilibili_room_not_stream(self):
        assert not is_stream_url("https://live.bilibili.com/12345")

    def test_douyin_room_not_stream(self):
        assert not is_stream_url("https://live.douyin.com/67890")


class TestGenericStreamAdapter:
    def setup_method(self):
        self.adapter = GenericStreamAdapter()

    def test_match_m3u8(self):
        assert self.adapter.match("https://cdn.example.com/hls/live.m3u8")

    def test_match_flv(self):
        assert self.adapter.match("https://cdn.example.com/live.flv")

    def test_match_rtmp(self):
        assert self.adapter.match("rtmp://push.example.com/live/stream")

    def test_no_match_webpage(self):
        assert not self.adapter.match("https://example.com/index.html")

    def test_platform(self):
        assert self.adapter.get_platform() == "generic"

    def test_check_live_returns_stream(self):
        result = self.adapter.check_live("https://cdn.example.com/hls/live.m3u8")
        assert result.platform == "generic"
        assert result.is_live is True
        assert result.stream_url == "https://cdn.example.com/hls/live.m3u8"
        assert "hls" in result.title.lower()

    def test_check_live_rtmp(self):
        result = self.adapter.check_live("rtmp://live.example.com/stream")
        assert result.platform == "generic"
        assert "rtmp" in result.title.lower()


# ── BilibiliAdapter ─────────────────────────────────────────


class TestBilibiliAdapter:
    def setup_method(self):
        self.adapter = BilibiliAdapter()

    def test_match_room_url(self):
        assert self.adapter.match("https://live.bilibili.com/12345")

    def test_match_room_with_path(self):
        assert self.adapter.match("https://live.bilibili.com/998877")

    def test_no_match_b23(self):
        assert not self.adapter.match("https://b23.tv/abcdef")

    def test_no_match_main_site(self):
        assert not self.adapter.match("https://www.bilibili.com/video/BV123")

    def test_platform(self):
        assert self.adapter.get_platform() == "bilibili"

    @patch("live2note.adapters.bilibili.BilibiliAdapter._yt_dlp_info")
    def test_check_live_success(self, mock_ytdlp):
        mock_ytdlp.return_value = {
            "title": "AI Learning Stream",
            "uploader": "TestStreamer",
            "is_live": True,
            "url": "https://pull-flv.live.bilibili.com/stream",
            "thumbnail": "https://i0.hdslb.com/cover.jpg",
        }
        result = self.adapter.check_live("https://live.bilibili.com/12345")
        assert result.platform == "bilibili"
        assert result.is_live is True
        assert result.title == "AI Learning Stream"
        assert result.streamer == "TestStreamer"
        assert result.room_id == "12345"
        assert result.stream_url == "https://pull-flv.live.bilibili.com/stream"
        assert result.error is None

    @patch("live2note.adapters.bilibili.BilibiliAdapter._yt_dlp_info")
    def test_check_live_not_live(self, mock_ytdlp):
        mock_ytdlp.return_value = {
            "title": "Offline Room",
            "uploader": "TestStreamer",
            "is_live": False,
        }
        result = self.adapter.check_live("https://live.bilibili.com/12345")
        assert result.is_live is False
        assert result.error is not None

    @patch("live2note.adapters.bilibili.BilibiliAdapter._yt_dlp_info")
    def test_check_live_ytdlp_error(self, mock_ytdlp):
        from live2note.adapters.bilibili import _YtdlpError

        mock_ytdlp.side_effect = _YtdlpError("HTTP Error 403")
        result = self.adapter.check_live("https://live.bilibili.com/12345")
        assert result.is_live is False
        assert "403" in result.error


# ── DouyinAdapter ───────────────────────────────────────────


class TestDouyinAdapter:
    def setup_method(self):
        self.adapter = DouyinAdapter()

    def test_match_live_douyin(self):
        assert self.adapter.match("https://live.douyin.com/123456789")

    def test_match_root_live(self):
        assert self.adapter.match("https://www.douyin.com/root/live/123456789")

    def test_no_match_main_site(self):
        assert not self.adapter.match("https://www.douyin.com/video/123")

    def test_platform(self):
        assert self.adapter.get_platform() == "douyin"

    @patch("live2note.adapters.douyin.DouyinAdapter._yt_dlp_info")
    def test_check_live_success(self, mock_ytdlp):
        mock_ytdlp.return_value = {
            "title": "Knowledge Sharing",
            "uploader": "DouyinStreamer",
            "is_live": True,
            "url": "https://pull-flv.douyin.com/stream.flv",
        }
        result = self.adapter.check_live("https://live.douyin.com/987654321")
        assert result.platform == "douyin"
        assert result.is_live is True
        assert result.title == "Knowledge Sharing"
        assert result.room_id == "987654321"

    @patch("live2note.adapters.douyin.DouyinAdapter._yt_dlp_info")
    def test_check_live_ytdlp_error_shows_generic_hint(self, mock_ytdlp):
        from live2note.adapters.douyin import _YtdlpError

        mock_ytdlp.side_effect = _YtdlpError("JS required")
        result = self.adapter.check_live("https://live.douyin.com/987654321")
        assert result.is_live is False
        assert result.live_status == "error"
        assert "streamlink" in result.error or "stream-url" in result.error


# ── Registry ────────────────────────────────────────────────


class TestRegistry:
    def test_get_adapter_bilibili(self):
        adapter = get_adapter("https://live.bilibili.com/12345")
        assert adapter is not None
        assert adapter.get_platform() == "bilibili"

    def test_get_adapter_douyin(self):
        adapter = get_adapter("https://live.douyin.com/999999999")
        assert adapter is not None
        assert adapter.get_platform() == "douyin"

    def test_get_adapter_generic_m3u8(self):
        adapter = get_adapter("https://cdn.example.com/live.m3u8")
        assert adapter is not None
        assert adapter.get_platform() == "generic"

    def test_get_adapter_by_name(self):
        assert get_adapter_by_name("bilibili") is not None
        assert get_adapter_by_name("douyin") is not None
        assert get_adapter_by_name("generic") is not None
        assert get_adapter_by_name("nonexistent") is None

    def test_get_adapter_or_raise_auto(self):
        adapter = get_adapter_or_raise("https://live.bilibili.com/1", "auto")
        assert adapter.get_platform() == "bilibili"

    def test_get_adapter_or_raise_explicit(self):
        adapter = get_adapter_or_raise("https://any.url", "generic")
        assert adapter.get_platform() == "generic"

    def test_get_adapter_or_raise_unknown(self):
        with pytest.raises(ValueError, match="Unknown platform"):
            get_adapter_or_raise("https://example.com", "nonexistent")

    def test_list_adapters(self):
        names = list_adapters()
        assert "bilibili" in names
        assert "douyin" in names
        assert "generic" in names
