"""Tests for FfmpegRecorder and StreamResolver."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from live2note.recorder.ffmpeg_recorder import FfmpegRecorder
from live2note.recorder.stream_resolver import StreamResolver

# ── FfmpegRecorder command builder ──────────────────────────


class TestBuildCommand:
    def setup_method(self):
        self.rec = FfmpegRecorder(ffmpeg_path="ffmpeg", sample_rate=16000, channels=1)

    def test_basic_command(self):
        out = Path("/tmp/seg_001.wav")
        cmd = self.rec._build_command(
            "https://cdn.example.com/live.m3u8",
            out,
            300,
        )
        assert cmd[0] == "ffmpeg"
        assert "-y" in cmd
        assert "-i" in cmd
        idx = cmd.index("-i")
        assert cmd[idx + 1] == "https://cdn.example.com/live.m3u8"
        t_idx = cmd.index("-t")
        assert cmd[t_idx + 1] == "300"
        a_idx = cmd.index("-acodec")
        assert cmd[a_idx + 1] == "pcm_s16le"
        ar_idx = cmd.index("-ar")
        assert cmd[ar_idx + 1] == "16000"
        ac_idx = cmd.index("-ac")
        assert cmd[ac_idx + 1] == "1"
        # Path is converted to string; on Windows it uses backslashes.
        assert cmd[-1] == str(out)

    def test_custom_ffmpeg_path(self):
        rec = FfmpegRecorder(ffmpeg_path="/usr/local/bin/ffmpeg")
        cmd = rec._build_command("https://x.com/s.flv", Path("/out.wav"), 60)
        assert cmd[0] == "/usr/local/bin/ffmpeg"

    def test_user_agent_present(self):
        cmd = self.rec._build_command("https://x.com/s.m3u8", Path("/o.wav"), 10)
        assert "-user_agent" in cmd
        ua_idx = cmd.index("-user_agent")
        assert "Mozilla" in cmd[ua_idx + 1]

    def test_vn_flag_present(self):
        cmd = self.rec._build_command("https://x.com/s.m3u8", Path("/o.wav"), 10)
        assert "-vn" in cmd


# ── FfmpegRecorder record (mocked ffmpeg) ───────────────────


def _make_mock_popen(returncode=0, stderr=b""):
    proc = MagicMock()
    proc.returncode = returncode
    proc.poll.return_value = returncode
    proc.communicate.return_value = (b"", stderr)
    proc.wait.return_value = None
    return proc


class TestRecordMocked:
    def test_records_segments(self, tmp_path: Path):
        rec = FfmpegRecorder()
        audio_dir = tmp_path / "audio_segments"

        def fake_popen(cmd, **kwargs):
            out_path = Path(cmd[-1])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"RIFF" + b"\x00" * 100)
            return _make_mock_popen(0)

        # total_seconds=2, segment_seconds=1 -> max_segments = 3
        with patch("live2note.recorder.ffmpeg_recorder.subprocess.Popen", side_effect=fake_popen):
            segments = rec.record(
                "https://example.com/live.m3u8",
                audio_dir,
                segment_seconds=1,
                total_seconds=2,
            )

        assert len(segments) >= 2
        assert segments[0]["file"].endswith("segment_001.wav")
        assert segments[1]["file"].endswith("segment_002.wav")

    def test_stops_at_total_duration(self, tmp_path: Path):
        rec = FfmpegRecorder()
        audio_dir = tmp_path / "audio_segments"
        call_count = 0

        def fake_popen(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            out_path = Path(cmd[-1])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"RIFF" + b"\x00" * 50)
            return _make_mock_popen(0)

        with patch("live2note.recorder.ffmpeg_recorder.subprocess.Popen", side_effect=fake_popen):
            segments = rec.record(
                "https://example.com/live.m3u8",
                audio_dir,
                segment_seconds=1,
                total_seconds=3,
            )

        assert 3 <= len(segments) <= 4
        assert call_count <= 4

    def test_empty_on_ffmpeg_failure(self, tmp_path: Path):
        rec = FfmpegRecorder()
        audio_dir = tmp_path / "audio_segments"

        def fake_popen(cmd, **kwargs):
            return _make_mock_popen(1, stderr=b"Error: stream not found")

        with patch("live2note.recorder.ffmpeg_recorder.subprocess.Popen", side_effect=fake_popen):
            segments = rec.record(
                "https://example.com/bad.m3u8",
                audio_dir,
                segment_seconds=1,
                total_seconds=2,
            )

        assert len(segments) == 0

    def test_stop_requested(self, tmp_path: Path):
        rec = FfmpegRecorder()
        audio_dir = tmp_path / "audio_segments"

        def fake_popen(cmd, **kwargs):
            out_path = Path(cmd[-1])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"RIFF" + b"\x00" * 50)
            # Request stop after first segment.
            rec._stop_requested = True
            return _make_mock_popen(0)

        with patch("live2note.recorder.ffmpeg_recorder.subprocess.Popen", side_effect=fake_popen):
            segments = rec.record(
                "https://example.com/live.m3u8",
                audio_dir,
                segment_seconds=1,
                total_seconds=100,
            )

        assert len(segments) == 1
        assert rec.stop_requested


# ── StreamResolver ──────────────────────────────────────────


class TestStreamResolver:
    def setup_method(self):
        from live2note.models.task import TaskState

        self.resolver = StreamResolver()
        self.state = TaskState(task_id="test", url="https://example.com")
        self.adapter = MagicMock()

    def test_explicit_override_wins(self):
        result = self.resolver.resolve(
            self.state, self.adapter, stream_url_override="https://cdn.com/direct.m3u8"
        )
        assert result == "https://cdn.com/direct.m3u8"
        self.adapter.resolve_stream_url.assert_not_called()

    def test_metadata_stream_url(self):
        self.state.metadata.stream_url = "https://cdn.com/from_check.m3u8"
        result = self.resolver.resolve(self.state, self.adapter)
        assert result == "https://cdn.com/from_check.m3u8"
        self.adapter.resolve_stream_url.assert_not_called()

    def test_adapter_resolve_fallback(self):
        self.adapter.resolve_stream_url.return_value = "https://cdn.com/resolved.flv"
        result = self.resolver.resolve(self.state, self.adapter)
        assert result == "https://cdn.com/resolved.flv"
        self.adapter.resolve_stream_url.assert_called_once_with("https://example.com")

    def test_adapter_resolve_empty_raises(self):
        self.adapter.resolve_stream_url.return_value = ""
        with pytest.raises(ValueError, match="Could not resolve"):
            self.resolver.resolve(self.state, self.adapter)

    def test_priority_order(self):
        self.state.metadata.stream_url = "https://metadata.com/s.m3u8"
        self.adapter.resolve_stream_url.return_value = "https://adapter.com/s.m3u8"
        result = self.resolver.resolve(
            self.state, self.adapter, stream_url_override="https://override.com/s.m3u8"
        )
        assert result == "https://override.com/s.m3u8"
