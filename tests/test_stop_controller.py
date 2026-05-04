"""Tests for StopController and LiveMonitor."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from live2note.models.task import StopReason, TaskState, TaskStatus
from live2note.recorder.stop_controller import (
    is_stop_flag_present,
    read_stop_flag,
    remove_stop_flag,
    request_stop,
    stop_ffmpeg,
    write_stop_flag,
)

# ── stop flag file operations ───────────────────────────────


def test_write_and_read_stop_flag(tmp_path: Path):
    write_stop_flag(tmp_path, StopReason.MANUAL_STOP.value)
    assert is_stop_flag_present(tmp_path)

    flag = read_stop_flag(tmp_path)
    assert flag is not None
    assert flag["reason"] == StopReason.MANUAL_STOP.value
    assert "time" in flag


def test_read_stop_flag_missing(tmp_path: Path):
    assert read_stop_flag(tmp_path) is None
    assert not is_stop_flag_present(tmp_path)


def test_remove_stop_flag(tmp_path: Path):
    write_stop_flag(tmp_path, "test")
    assert is_stop_flag_present(tmp_path)
    remove_stop_flag(tmp_path)
    assert not is_stop_flag_present(tmp_path)


def test_remove_nonexistent_flag(tmp_path: Path):
    remove_stop_flag(tmp_path)  # should not raise


# ── request_stop ────────────────────────────────────────────


def test_request_stop_updates_state(tmp_path: Path):
    state = TaskState(task_id="t", url="u", status=TaskStatus.RECORDING.value)
    request_stop(state, tmp_path, StopReason.MANUAL_STOP.value)

    assert state.stop_requested is True
    assert state.stop_reason == StopReason.MANUAL_STOP.value
    assert state.stop_requested_at is not None
    assert state.status == TaskStatus.STOP_REQUESTED.value
    assert is_stop_flag_present(tmp_path)


def test_request_stop_non_recording_state(tmp_path: Path):
    state = TaskState(task_id="t", url="u", status=TaskStatus.TRANSCRIBING.value)
    request_stop(state, tmp_path)

    assert state.stop_requested is True
    # Status should NOT change to STOP_REQUESTED when not recording.
    assert state.status == TaskStatus.TRANSCRIBING.value


# ── stop_ffmpeg ─────────────────────────────────────────────


def test_stop_ffmpeg_no_pid():
    state = TaskState(task_id="t", url="u")
    assert stop_ffmpeg(state) is True


@patch("live2note.recorder.stop_controller._is_process_alive", return_value=False)
def test_stop_ffmpeg_already_exited(mock_alive):
    state = TaskState(task_id="t", url="u", ffmpeg_pid=12345)
    assert stop_ffmpeg(state) is True


# ── TaskState stop helpers ──────────────────────────────────


def test_mark_stopped_sets_fields():
    state = TaskState(task_id="t", url="u")
    state.mark_stopped(StopReason.LIVE_ENDED.value)
    assert state.status == TaskStatus.STOPPED.value
    assert state.stop_reason == StopReason.LIVE_ENDED.value
    assert state.stopped_at is not None
    assert state.stop_requested is False


def test_request_stop():
    state = TaskState(task_id="t", url="u", status=TaskStatus.RECORDING.value)
    state.request_stop(StopReason.MANUAL_STOP.value)
    assert state.stop_requested is True
    assert state.stop_reason == StopReason.MANUAL_STOP.value
    assert state.status == TaskStatus.STOP_REQUESTED.value


def test_mark_finalizing():
    state = TaskState(task_id="t", url="u")
    state.mark_finalizing()
    assert state.status == TaskStatus.FINALIZING.value


def test_mark_completed_with_stop():
    state = TaskState(task_id="t", url="u")
    state.mark_completed_with_stop()
    assert state.status == TaskStatus.COMPLETED_WITH_MANUAL_STOP.value
    assert state.stop_requested is False


def test_record_segment_time():
    state = TaskState(task_id="t", url="u")
    assert state.last_segment_at is None
    state.record_segment_time()
    assert state.last_segment_at is not None


def test_record_stream_check():
    state = TaskState(task_id="t", url="u")
    state.record_stream_check(True)
    assert state.live_status == "live"
    assert state.last_stream_check_at is not None

    state.record_stream_check(False)
    assert state.live_status == "ended"


def test_new_fields_serialization():
    state = TaskState(task_id="t", url="u")
    state.ffmpeg_pid = 12345
    state.stop_requested = True
    state.stop_reason = "manual_stop"
    state.live_status = "ended"
    state.last_segment_at = "2026-05-05T00:00:00Z"

    d = state.to_dict()
    assert d["ffmpeg_pid"] == 12345
    assert d["stop_requested"] is True
    assert d["stop_reason"] == "manual_stop"
    assert d["live_status"] == "ended"

    restored = TaskState.from_dict(d)
    assert restored.ffmpeg_pid == 12345
    assert restored.stop_requested is True
    assert restored.stop_reason == "manual_stop"
    assert restored.live_status == "ended"


def test_backward_compat():
    """Old task_state.json without new fields should default gracefully."""
    data = {"task_id": "t", "url": "u"}
    state = TaskState.from_dict(data)
    assert state.ffmpeg_pid is None
    assert state.stop_requested is False
    assert state.stop_reason is None
    assert state.live_status == "unknown"
