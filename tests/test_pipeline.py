"""Tests for the Pipeline executor."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from live2note.config import AppConfig
from live2note.models.task import TaskState, TaskStatus
from live2note.pipeline import Pipeline
from live2note.task_manager import TaskManager


def _make_cfg(tmp_path: Path) -> AppConfig:
    """Create a minimal AppConfig with tmp_path as base_dir."""
    cfg = AppConfig()
    # Override output base_dir.
    object.__setattr__(cfg, "output", type(cfg.output)(
        base_dir=tmp_path / "tasks",
        keep_audio=True,
        keep_intermediate=True,
    ))
    return cfg


def _create_task_with_segments(mgr: TaskManager, tmp_path: Path) -> TaskState:
    """Create a task and populate audio_segments with fake WAV files."""
    state = mgr.create("https://example.com/live.m3u8", platform="generic")
    task_dir = mgr.base_dir / state.task_id

    audio_dir = task_dir / "audio_segments"
    audio_dir.mkdir(parents=True, exist_ok=True)

    wav = audio_dir / "segment_001.wav"
    wav.write_bytes(b"RIFF" + b"\x00" * 100)

    state.audio_segments = [{"index": 1, "file": str(wav), "duration": 5.0}]
    mgr.save(state)
    return state


# ── Pipeline skips completed steps ──────────────────────────


def test_pipeline_skips_completed_steps(tmp_path: Path):
    cfg = _make_cfg(tmp_path)
    mgr = TaskManager(cfg.output.base_dir)

    state = mgr.create("https://example.com/live.m3u8", platform="generic")
    # Mark all steps done.
    for step in ["check", "record", "transcribe", "process", "summarize", "save", "import_getnote"]:
        state.finish_step(step)
    mgr.save(state)

    pipeline = Pipeline(mgr, cfg)
    result = pipeline.run(state)

    assert result.status == TaskStatus.COMPLETED.value


# ── Pipeline fails gracefully ───────────────────────────────


def test_pipeline_fails_on_missing_audio(tmp_path: Path):
    cfg = _make_cfg(tmp_path)
    mgr = TaskManager(cfg.output.base_dir)

    state = mgr.create("https://example.com/live.m3u8", platform="generic")
    state.finish_step("check")
    state.finish_step("record")
    mgr.save(state)

    pipeline = Pipeline(mgr, cfg)
    result = pipeline.run(state)

    assert result.status == TaskStatus.FAILED.value
    assert result.error_message is not None
    assert "transcribe" in result.error_message.lower()


# ── Pipeline with mocked transcriber ────────────────────────


def test_pipeline_transcribe_step(tmp_path: Path):
    cfg = _make_cfg(tmp_path)
    mgr = TaskManager(cfg.output.base_dir)

    state = _create_task_with_segments(mgr, tmp_path)
    state.finish_step("check")
    state.finish_step("record")
    mgr.save(state)

    mock_segments = [
        MagicMock(start=0.0, end=5.0, text="test transcription", confidence=-0.1, speaker=""),
    ]

    with patch("live2note.transcriber.WhisperEngine") as MockEngine:
        instance = MockEngine.return_value
        instance.transcribe.return_value = mock_segments

        pipeline = Pipeline(mgr, cfg)
        # Skip process+save to focus on transcribe.
        with patch.object(pipeline, "_step_process", side_effect=lambda s, d: s):
            with patch.object(pipeline, "_step_save", side_effect=lambda s, d: s):
                result = pipeline.run(state)

    # Transcribe should have completed.
    assert result.is_step_done("transcribe")
    assert len(result.transcripts) == 1


# ── Pipeline with full mocked flow ──────────────────────────


def test_pipeline_full_mocked_flow(tmp_path: Path):
    cfg = _make_cfg(tmp_path)
    mgr = TaskManager(cfg.output.base_dir)

    state = _create_task_with_segments(mgr, tmp_path)
    state.finish_step("check")
    state.finish_step("record")
    mgr.save(state)

    task_dir = mgr.base_dir / state.task_id

    # Create transcript files for process step.
    transcripts_dir = task_dir / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    transcript = {
        "segment_id": 1, "audio_file": "segment_001.wav", "global_offset": 0.0,
        "segment_count": 1,
        "segments": [
            {"start": 0.0, "end": 5.0, "global_start": 0.0, "global_end": 5.0,
             "text": "test content for processing", "confidence": -0.1},
        ],
    }
    (transcripts_dir / "segment_001.json").write_text(
        json.dumps(transcript, ensure_ascii=False), encoding="utf-8"
    )
    state.add_transcript(1, str(transcripts_dir / "segment_001.json"))
    state.finish_step("transcribe")
    mgr.save(state)

    pipeline = Pipeline(mgr, cfg)

    # Mock summarizer to avoid LLM calls.
    MagicMock(
        chunk_id=1, start=0.0, end=5.0,
        summary="Test summary", key_points=["KP1"],
        knowledge_points=["KP1"], action_items=["AI1"],
        tags=["test"], keywords=["kw"], important_quotes=["quote"],
    )
    with patch("live2note.processor.summarizer.Summarizer") as MockSum:
        MockSum.return_value.is_configured = False  # skip summarization
        result = pipeline.run(state)

    assert result.status == TaskStatus.COMPLETED.value
    assert result.is_step_done("transcribe")
    assert result.is_step_done("process")
    assert result.is_step_done("save")
    assert result.final_note_path is not None


# ── Resume integration ──────────────────────────────────────


def test_resume_continues_pipeline(tmp_path: Path):
    cfg = _make_cfg(tmp_path)
    mgr = TaskManager(cfg.output.base_dir)

    state = mgr.create("https://example.com/live.m3u8", platform="generic")
    state.finish_step("check")
    state.finish_step("record")
    state.finish_step("transcribe")
    state.finish_step("process")
    state.mark_failed("summarize: timeout")
    mgr.save(state)

    # Resume should retry from summarize.
    resumed = mgr.resume(state.task_id)
    assert resumed.retry_count == 1
    assert resumed.current_step == "summarize"
