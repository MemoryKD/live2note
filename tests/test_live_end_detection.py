"""Tests for live end detection: LiveMonitor, FfmpegRecorder reconnect, state transitions."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from live2note.models.task import (
    LiveCheckStatus,
    StopReason,
    TaskState,
    TaskStatus,
)
from live2note.recorder.ffmpeg_recorder import FfmpegRecorder
from live2note.recorder.live_monitor import LiveMonitor

# ── TaskState transition tests (new methods) ──────────────────


class TestTaskStateLiveEnd:
    def test_mark_reconnecting(self):
        state = TaskState(task_id="t", url="u")
        state.mark_reconnecting()
        assert state.status == TaskStatus.RECONNECTING.value
        assert state.reconnect_count == 1
        state.mark_reconnecting()
        assert state.reconnect_count == 2

    def test_mark_live_ended_confirmed(self):
        state = TaskState(task_id="t", url="u")
        state.mark_live_ended_confirmed()
        assert state.status == TaskStatus.LIVE_ENDED.value
        assert state.confirmed_live_ended_at is not None
        assert state.suspected_live_ended_at is None  # not set by this method

    def test_mark_suspected_live_ended(self):
        state = TaskState(task_id="t", url="u")
        state.mark_suspected_live_ended()
        assert state.status == TaskStatus.SUSPECTED_LIVE_ENDED.value
        assert state.suspected_live_ended_at is not None

    def test_mark_stream_interrupted(self):
        state = TaskState(task_id="t", url="u")
        state.mark_stream_interrupted()
        assert state.status == TaskStatus.STREAM_INTERRUPTED.value

    def test_record_live_check(self):
        state = TaskState(task_id="t", url="u")
        state.record_live_check(LiveCheckStatus.LIVE.value)
        assert state.last_live_check_result == LiveCheckStatus.LIVE.value
        assert state.last_live_check_at is not None
        assert state.live_status == "live"

        state.record_live_check(LiveCheckStatus.NOT_LIVE.value)
        assert state.live_status == "not_live"

        state.record_live_check(LiveCheckStatus.ERROR.value)
        assert state.live_status == "error"

        state.record_live_check(LiveCheckStatus.UNKNOWN.value)
        assert state.live_status == "unknown"

    def test_set_ffmpeg_exit_info(self):
        state = TaskState(task_id="t", url="u")
        state.set_ffmpeg_exit_info(1, "Error: bad stream")
        assert state.last_ffmpeg_exit_code == 1
        assert "bad stream" in state.last_ffmpeg_stderr_tail


# ── LiveMonitor tests ─────────────────────────────────────────


def _make_monitor(
    state=None,
    live_end_confirmations=3,
    max_failures=5,
    interval=60,
):
    if state is None:
        state = TaskState(task_id="t", url="https://example.com/live")
    task_dir = Path("/tmp/tasks/t")
    check_fn = MagicMock(return_value=MagicMock())
    stop_fn = MagicMock()
    save_fn = MagicMock()

    monitor = LiveMonitor(
        state=state,
        task_dir=task_dir,
        check_live_fn=check_fn,
        stop_fn=stop_fn,
        save_fn=save_fn,
        interval_seconds=interval,
        max_failures=max_failures,
        live_end_confirmations=live_end_confirmations,
    )
    return monitor, check_fn, stop_fn, save_fn


class TestLiveMonitorCheckOnce:
    """Test LiveMonitor._check_once for each live_status value."""

    def test_live_resets_counters(self):
        monitor, check_fn, stop_fn, save_fn = _make_monitor()
        monitor._consecutive_failures = 3
        monitor._state.live_end_confirm_count = 2
        check_fn.return_value = MagicMock(live_status=LiveCheckStatus.LIVE.value)

        monitor._check_once()

        assert monitor._consecutive_failures == 0
        assert monitor._state.live_end_confirm_count == 0
        stop_fn.assert_not_called()

    def test_not_live_increments_confirm_count(self):
        monitor, check_fn, stop_fn, save_fn = _make_monitor(live_end_confirmations=3)
        check_fn.return_value = MagicMock(live_status=LiveCheckStatus.NOT_LIVE.value)

        # First NOT_LIVE
        monitor._check_once()
        assert monitor._state.live_end_confirm_count == 1
        stop_fn.assert_not_called()

        # Second NOT_LIVE
        monitor._check_once()
        assert monitor._state.live_end_confirm_count == 2
        stop_fn.assert_not_called()

        # Third NOT_LIVE triggers stop
        monitor._check_once()
        assert monitor._state.live_end_confirm_count == 3
        stop_fn.assert_called_once()
        args = stop_fn.call_args[0]
        assert args[2] == StopReason.LIVE_ENDED_CONFIRMED.value

    def test_not_live_resets_error_counter(self):
        """NOT_LIVE should reset the error counter (definitive answer)."""
        monitor, check_fn, stop_fn, save_fn = _make_monitor()
        monitor._consecutive_failures = 4

        check_fn.return_value = MagicMock(live_status=LiveCheckStatus.NOT_LIVE.value)
        monitor._check_once()

        assert monitor._consecutive_failures == 0

    def test_error_does_not_increment_live_end_confirm(self):
        """ERROR should not increment live_end_confirm_count."""
        monitor, check_fn, stop_fn, save_fn = _make_monitor(max_failures=5)
        check_fn.return_value = MagicMock(live_status=LiveCheckStatus.ERROR.value)

        for _ in range(3):
            monitor._check_once()

        assert monitor._state.live_end_confirm_count == 0
        assert monitor._consecutive_failures == 3
        stop_fn.assert_not_called()

    def test_error_triggers_stop_after_max_failures(self):
        monitor, check_fn, stop_fn, save_fn = _make_monitor(max_failures=2)
        check_fn.return_value = MagicMock(live_status=LiveCheckStatus.ERROR.value)

        monitor._check_once()  # 1
        stop_fn.assert_not_called()
        monitor._check_once()  # 2 → triggers stop
        stop_fn.assert_called_once()
        args = stop_fn.call_args[0]
        assert args[2] == StopReason.STREAM_INTERRUPTED.value

    def test_unknown_same_as_error(self):
        monitor, check_fn, stop_fn, save_fn = _make_monitor(max_failures=2)
        check_fn.return_value = MagicMock(live_status=LiveCheckStatus.UNKNOWN.value)

        monitor._check_once()  # 1
        stop_fn.assert_not_called()
        monitor._check_once()  # 2 → triggers stop
        stop_fn.assert_called_once()
        args = stop_fn.call_args[0]
        assert args[2] == StopReason.STREAM_INTERRUPTED.value

    def test_live_after_error_resets_error_counter(self):
        """A LIVE result after errors should reset the error counter."""
        monitor, check_fn, stop_fn, save_fn = _make_monitor(max_failures=3)
        check_fn.return_value = MagicMock(live_status=LiveCheckStatus.ERROR.value)

        monitor._check_once()  # error 1
        monitor._check_once()  # error 2
        assert monitor._consecutive_failures == 2

        check_fn.return_value = MagicMock(live_status=LiveCheckStatus.LIVE.value)
        monitor._check_once()

        assert monitor._consecutive_failures == 0

    def test_mixed_sequence(self):
        """Simulate a realistic sequence with errors followed by not_live."""
        monitor, check_fn, stop_fn, save_fn = _make_monitor(
            live_end_confirmations=3, max_failures=5
        )

        def check(live_status):
            check_fn.return_value = MagicMock(live_status=live_status)
            monitor._check_once()

        check(LiveCheckStatus.LIVE.value)      # live
        assert monitor._state.live_end_confirm_count == 0
        assert monitor._consecutive_failures == 0

        check(LiveCheckStatus.ERROR.value)      # error (network glitch)
        assert monitor._state.live_end_confirm_count == 0
        assert monitor._consecutive_failures == 1

        check(LiveCheckStatus.ERROR.value)      # another error
        assert monitor._consecutive_failures == 2

        check(LiveCheckStatus.LIVE.value)       # back to live
        assert monitor._consecutive_failures == 0
        assert monitor._state.live_end_confirm_count == 0
        stop_fn.assert_not_called()

    def test_does_not_trigger_stop_on_insufficient_not_live(self):
        """1-2 NOT_LIVE should not trigger stop when threshold is 3."""
        monitor, check_fn, stop_fn, save_fn = _make_monitor(live_end_confirmations=3)
        check_fn.return_value = MagicMock(live_status=LiveCheckStatus.NOT_LIVE.value)

        monitor._check_once()
        monitor._check_once()
        assert stop_fn.call_count == 0

    def test_custom_live_end_confirmations(self):
        """Use a different threshold for live end confirmations."""
        monitor, check_fn, stop_fn, save_fn = _make_monitor(live_end_confirmations=1)
        check_fn.return_value = MagicMock(live_status=LiveCheckStatus.NOT_LIVE.value)

        monitor._check_once()
        stop_fn.assert_called_once()

    def test_stop_fn_receives_correct_reason(self):
        monitor, check_fn, stop_fn, save_fn = _make_monitor(live_end_confirmations=1)
        check_fn.return_value = MagicMock(live_status=LiveCheckStatus.NOT_LIVE.value)

        monitor._check_once()
        args, _ = stop_fn.call_args
        assert args[2] == StopReason.LIVE_ENDED_CONFIRMED.value

    def test_default_live_status_fallback(self):
        """CheckResult without live_status should fall back to UNKNOWN."""
        monitor, check_fn, stop_fn, save_fn = _make_monitor(max_failures=1)
        # Mock without live_status attribute
        result = MagicMock()
        del result.live_status
        check_fn.return_value = result

        monitor._check_once()
        assert monitor._consecutive_failures == 1


# ── FfmpegRecorder reconnect tests ────────────────────────────


def _make_mock_popen(returncode=0, stderr=b""):
    proc = MagicMock()
    proc.returncode = returncode
    proc.poll.return_value = returncode
    proc.communicate.return_value = (b"", stderr)
    proc.wait.return_value = None
    return proc


class TestFfmpegRecorderReconnect:
    def test_single_ffmpeg_failure_reconnects(self, tmp_path: Path):
        """One ffmpeg failure should trigger reconnect, not stop."""
        rec = FfmpegRecorder()
        audio_dir = tmp_path / "audio_segments"
        call_count = [0]

        def fake_popen(cmd, **kwargs):
            out_path = Path(cmd[-1])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            call_count[0] += 1
            # First call fails, second succeeds
            if call_count[0] == 1:
                return _make_mock_popen(1, stderr=b"stream expired")
            out_path.write_bytes(b"RIFF" + b"\x00" * 100)
            return _make_mock_popen(0)

        reconnect_results = iter([
            "https://cdn.com/new-stream.m3u8",  # fresh URL for reconnect
        ])

        def reconnect_fn(seg_index, attempt):
            return next(reconnect_results)

        with patch("live2note.recorder.ffmpeg_recorder.subprocess.Popen", side_effect=fake_popen):
            segments = rec.record(
                "https://example.com/live.m3u8",
                audio_dir,
                segment_seconds=1,
                total_seconds=2,
                reconnect_fn=reconnect_fn,
                max_reconnect_attempts=3,
                reconnect_delay=0,
            )

        assert len(segments) >= 1
        assert call_count[0] >= 2
        assert not rec.stop_requested

    def test_all_reconnect_attempts_fail(self, tmp_path: Path):
        """When all reconnects fail, recording should stop."""
        rec = FfmpegRecorder()
        audio_dir = tmp_path / "audio_segments"

        def fake_popen(cmd, **kwargs):
            return _make_mock_popen(1, stderr=b"stream not found")

        reconnect_calls = []

        def reconnect_fn(seg_index, attempt):
            reconnect_calls.append(attempt)
            return None  # abort all reconnects

        with patch("live2note.recorder.ffmpeg_recorder.subprocess.Popen", side_effect=fake_popen):
            segments = rec.record(
                "https://example.com/live.m3u8",
                audio_dir,
                segment_seconds=1,
                total_seconds=2,
                reconnect_fn=reconnect_fn,
                max_reconnect_attempts=3,
                reconnect_delay=0,
            )

        assert len(segments) == 0
        assert len(reconnect_calls) == 1  # first attempt, which returns None (abort)

    def test_reconnect_retries_on_fresh_url(self, tmp_path: Path):
        """Reconnect should use the URL from reconnect_fn for retry."""
        rec = FfmpegRecorder()
        audio_dir = tmp_path / "audio_segments"
        call_count = [0]

        def fake_popen(cmd, **kwargs):
            out_path = Path(cmd[-1])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_mock_popen(1, stderr=b"expired")
            out_path.write_bytes(b"RIFF" + b"\x00" * 100)
            return _make_mock_popen(0)

        def reconnect_fn(seg_index, attempt):
            return "https://fresh-url.com/stream.m3u8"

        with patch("live2note.recorder.ffmpeg_recorder.subprocess.Popen", side_effect=fake_popen):
            segments = rec.record(
                "https://example.com/live.m3u8",
                audio_dir,
                segment_seconds=1,
                total_seconds=2,
                reconnect_fn=reconnect_fn,
                max_reconnect_attempts=5,
                reconnect_delay=0,
            )

        assert len(segments) >= 1
        assert rec.last_ffmpeg_exit_code == 0  # last ffmpeg should have succeeded

    def test_no_reconnect_fn_keeps_old_behavior(self, tmp_path: Path):
        """No reconnect_fn means single ffmpeg failure stops recording."""
        rec = FfmpegRecorder()
        audio_dir = tmp_path / "audio_segments"

        def fake_popen(cmd, **kwargs):
            return _make_mock_popen(1, stderr=b"error")

        with patch("live2note.recorder.ffmpeg_recorder.subprocess.Popen", side_effect=fake_popen):
            segments = rec.record(
                "https://example.com/live.m3u8",
                audio_dir,
                segment_seconds=1,
                total_seconds=2,
                reconnect_fn=None,
            )

        assert len(segments) == 0

    def test_ffmpeg_exit_recorded_on_failure(self, tmp_path: Path):
        """ffmpeg exit code and stderr should be recorded on failure."""
        rec = FfmpegRecorder()
        audio_dir = tmp_path / "audio_segments"

        def fake_popen(cmd, **kwargs):
            return _make_mock_popen(1, stderr=b"Error: stream not found")

        with patch("live2note.recorder.ffmpeg_recorder.subprocess.Popen", side_effect=fake_popen):
            rec.record(
                "https://example.com/live.m3u8",
                audio_dir,
                segment_seconds=1,
                total_seconds=2,
            )

        assert rec.last_ffmpeg_exit_code == 1
        assert rec.last_ffmpeg_stderr is not None
        assert "stream not found" in rec.last_ffmpeg_stderr

    def test_ffmpeg_exit_recorded_on_success(self, tmp_path: Path):
        """ffmpeg exit code should be 0 on success."""
        rec = FfmpegRecorder()
        audio_dir = tmp_path / "audio_segments"

        def fake_popen(cmd, **kwargs):
            out_path = Path(cmd[-1])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"RIFF" + b"\x00" * 100)
            return _make_mock_popen(0)

        with patch("live2note.recorder.ffmpeg_recorder.subprocess.Popen", side_effect=fake_popen):
            rec.record(
                "https://example.com/live.m3u8",
                audio_dir,
                segment_seconds=1,
                total_seconds=2,
            )

        assert rec.last_ffmpeg_exit_code == 0
