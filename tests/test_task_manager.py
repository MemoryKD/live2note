"""Tests for TaskManager: create, load, list, save, resume."""

from __future__ import annotations

from pathlib import Path

import pytest

from live2note.models.task import PIPELINE_STEPS, TaskStatus
from live2note.task_manager import TaskManager


@pytest.fixture()
def mgr(tmp_path: Path) -> TaskManager:
    return TaskManager(tmp_path / "tasks")


# ── create ──────────────────────────────────────────────────


def test_create_returns_state(mgr: TaskManager):
    state = mgr.create("https://live.bilibili.com/12345")
    assert state.task_id
    assert state.status == TaskStatus.CREATED.value
    assert state.source_type == "bilibili"
    assert state.url == "https://live.bilibili.com/12345"


def test_create_makedirs(mgr: TaskManager):
    state = mgr.create("https://example.com/live.m3u8")
    t_dir = mgr.base_dir / state.task_id
    assert (t_dir / "task_state.json").is_file()
    assert (t_dir / "metadata.json").is_file()
    assert (t_dir / "audio_segments").is_dir()
    assert (t_dir / "transcripts").is_dir()
    assert (t_dir / "notes").is_dir()
    assert (t_dir / "logs").is_dir()


def test_create_detects_platform(mgr: TaskManager):
    assert mgr.create("https://live.bilibili.com/1").source_type == "bilibili"
    assert mgr.create("https://live.douyin.com/1").source_type == "douyin"
    assert mgr.create("https://example.com/live.m3u8").source_type == "generic"
    assert mgr.create("rtmp://stream.example.com/live").source_type == "generic"


def test_create_explicit_platform(mgr: TaskManager):
    state = mgr.create("https://example.com/live", platform="bilibili")
    assert state.source_type == "bilibili"


# ── load ────────────────────────────────────────────────────


def test_load_roundtrip(mgr: TaskManager):
    original = mgr.create("https://live.bilibili.com/1", duration=10, getnote=True)
    loaded = mgr.load(original.task_id)

    assert loaded.task_id == original.task_id
    assert loaded.url == original.url
    assert loaded.duration == 10
    assert loaded.getnote_tags == []
    assert loaded.status == TaskStatus.CREATED.value
    assert loaded.finished_steps == []
    assert loaded.audio_segments == []


def test_load_not_found(mgr: TaskManager):
    with pytest.raises(FileNotFoundError):
        mgr.load("nonexistent_id")


# ── list ────────────────────────────────────────────────────


def test_list_empty(mgr: TaskManager):
    assert mgr.list_tasks() == []


def test_list_returns_all(mgr: TaskManager):
    mgr.create("https://a.com")
    mgr.create("https://b.com")
    mgr.create("https://c.com")
    assert len(mgr.list_tasks()) == 3


def test_list_respects_limit(mgr: TaskManager):
    for i in range(5):
        mgr.create(f"https://example.com/{i}")
    assert len(mgr.list_tasks(limit=2)) == 2


def test_list_status_filter(mgr: TaskManager):
    s1 = mgr.create("https://a.com")
    s2 = mgr.create("https://b.com")
    s1.set_status(TaskStatus.FAILED)
    mgr.save(s1)

    failed = mgr.list_tasks(status_filter=TaskStatus.FAILED.value)
    assert len(failed) == 1
    assert failed[0].task_id == s1.task_id

    created = mgr.list_tasks(status_filter=TaskStatus.CREATED.value)
    assert len(created) == 1
    assert created[0].task_id == s2.task_id


# ── save ────────────────────────────────────────────────────


def test_save_persists_changes(mgr: TaskManager):
    state = mgr.create("https://example.com")
    state.set_step("record")
    state.finish_step("check")
    state.add_audio_segment(1, "audio_segments/segment_001.wav", 300.0)
    mgr.save(state)

    loaded = mgr.load(state.task_id)
    assert loaded.current_step == "record"
    assert loaded.finished_steps == ["check"]
    assert loaded.audio_segments == [{"index": 1, "file": "audio_segments/segment_001.wav", "duration": 300.0}]


# ── get_latest ──────────────────────────────────────────────


def test_get_latest_none(mgr: TaskManager):
    assert mgr.get_latest() is None


def test_get_latest_returns_most_recent(mgr: TaskManager):
    mgr.create("https://a.com")
    s2 = mgr.create("https://b.com")
    latest = mgr.get_latest()
    assert latest is not None
    assert latest.task_id == s2.task_id


# ── task_exists ─────────────────────────────────────────────


def test_task_exists(mgr: TaskManager):
    state = mgr.create("https://example.com")
    assert mgr.task_exists(state.task_id)
    assert not mgr.task_exists("nonexistent")


# ── resume ──────────────────────────────────────────────────


def test_resume_from_created(mgr: TaskManager):
    state = mgr.create("https://example.com")
    resumed = mgr.resume(state.task_id)

    assert resumed.retry_count == 1
    assert resumed.current_step == "check"
    assert resumed.status == TaskStatus.CHECKING.value


def test_resume_increments_retry(mgr: TaskManager):
    state = mgr.create("https://example.com")
    mgr.resume(state.task_id)
    mgr.resume(state.task_id)
    loaded = mgr.load(state.task_id)
    assert loaded.retry_count == 2


def test_resume_from_failed(mgr: TaskManager):
    state = mgr.create("https://example.com")
    state.finish_step("check")
    state.set_step("record")
    state.mark_failed("ffmpeg crashed")
    mgr.save(state)

    resumed = mgr.resume(state.task_id)
    assert resumed.retry_count == 1
    assert resumed.current_step == "record"
    assert resumed.error_message is None
    assert resumed.status == TaskStatus.RECORDING.value
    assert "check" in resumed.finished_steps


def test_resume_skips_completed_steps(mgr: TaskManager):
    state = mgr.create("https://example.com")
    state.finish_step("check")
    state.finish_step("record")
    state.finish_step("transcribe")
    mgr.save(state)

    resumed = mgr.resume(state.task_id)
    assert resumed.current_step == "process"
    assert resumed.status == TaskStatus.PROCESSING.value


def test_resume_completed_task(mgr: TaskManager):
    state = mgr.create("https://example.com")
    for step in PIPELINE_STEPS:
        state.finish_step(step)
    state.mark_completed()
    mgr.save(state)

    resumed = mgr.resume(state.task_id)
    assert resumed.status == TaskStatus.COMPLETED.value


def test_resume_nonexistent(mgr: TaskManager):
    with pytest.raises(FileNotFoundError):
        mgr.resume("nonexistent")
