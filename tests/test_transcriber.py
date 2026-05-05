"""Tests for WhisperEngine, transcript_writer, and transcribe CLI command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from live2note.transcriber.transcript_writer import (
    _fmt_ts,
    write_transcript_json,
    write_transcript_markdown,
)
from live2note.transcriber.whisper_engine import Segment, WhisperEngine

# ── Segment ─────────────────────────────────────────────────


def test_segment_dataclass():
    s = Segment(start=0.0, end=3.5, text="hello world", confidence=-0.2)
    assert s.start == 0.0
    assert s.end == 3.5
    assert s.text == "hello world"
    assert s.confidence == -0.2


# ── _fmt_ts ─────────────────────────────────────────────────


def test_fmt_ts_seconds():
    assert _fmt_ts(65.0) == "01:05"


def test_fmt_ts_minutes():
    assert _fmt_ts(300.0) == "05:00"


def test_fmt_ts_hours():
    assert _fmt_ts(3661.0) == "01:01:01"


def test_fmt_ts_zero():
    assert _fmt_ts(0.0) == "00:00"


# ── write_transcript_json ───────────────────────────────────


def test_write_json_basic(tmp_path: Path):
    out = tmp_path / "segment_001.json"
    segments = [
        Segment(start=0.0, end=3.5, text="hello", confidence=-0.1),
        Segment(start=3.5, end=7.0, text="world", confidence=-0.2),
    ]
    write_transcript_json(out, 1, "segment_001.wav", segments, global_offset=0.0)

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["segment_id"] == 1
    assert data["audio_file"] == "segment_001.wav"
    assert data["global_offset"] == 0.0
    assert data["segment_count"] == 2
    assert data["segments"][0]["start"] == 0.0
    assert data["segments"][0]["global_start"] == 0.0
    assert data["segments"][1]["start"] == 3.5
    assert data["segments"][1]["global_end"] == 7.0


def test_write_json_with_offset(tmp_path: Path):
    out = tmp_path / "segment_002.json"
    segments = [
        Segment(start=0.0, end=5.0, text="second segment", confidence=-0.15),
    ]
    write_transcript_json(out, 2, "segment_002.wav", segments, global_offset=300.0)

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["global_offset"] == 300.0
    assert data["segments"][0]["start"] == 0.0
    assert data["segments"][0]["global_start"] == 300.0
    assert data["segments"][0]["global_end"] == 305.0


# ── write_transcript_markdown ───────────────────────────────


def test_write_markdown_basic(tmp_path: Path):
    out = tmp_path / "segment_001.md"
    segments = [
        Segment(start=0.0, end=3.5, text="hello", confidence=-0.1),
        Segment(start=3.5, end=7.0, text="world", confidence=-0.2),
    ]
    write_transcript_markdown(out, 1, "segment_001.wav", segments, global_offset=0.0)

    content = out.read_text(encoding="utf-8")
    assert "Segment 001" in content
    assert "segment_001.wav" in content
    assert "[00:00] hello" in content
    assert "[00:03] world" in content


def test_write_markdown_with_offset(tmp_path: Path):
    out = tmp_path / "segment_002.md"
    segments = [
        Segment(start=0.0, end=5.0, text="second", confidence=-0.1),
    ]
    write_transcript_markdown(out, 2, "segment_002.wav", segments, global_offset=300.0)

    content = out.read_text(encoding="utf-8")
    assert "[05:00] second" in content
    assert "05:00" in content  # segment start timestamp


def test_write_markdown_empty(tmp_path: Path):
    out = tmp_path / "segment_empty.md"
    write_transcript_markdown(out, 3, "empty.wav", [], global_offset=0.0)
    content = out.read_text(encoding="utf-8")
    assert "Segment 003" in content
    assert "Segments: 0" in content


# ── WhisperEngine (mocked) ──────────────────────────────────


def _mock_whisper_segments():
    """Return mock faster-whisper segment objects."""
    seg1 = MagicMock()
    seg1.start = 0.0
    seg1.end = 3.5
    seg1.text = " hello "
    seg1.avg_logprob = -0.15

    seg2 = MagicMock()
    seg2.start = 3.5
    seg2.end = 7.2
    seg2.text = " world "
    seg2.avg_logprob = -0.25

    return [seg1, seg2]


class TestWhisperEngine:
    def test_transcribe_returns_segments(self, tmp_path: Path):
        audio = tmp_path / "test.wav"
        audio.write_bytes(b"RIFF" + b"\x00" * 100)

        mock_model = MagicMock()
        mock_info = MagicMock()
        mock_info.language = "zh"
        mock_info.language_probability = 0.95
        mock_model.transcribe.return_value = (iter(_mock_whisper_segments()), mock_info)

        engine = WhisperEngine(model_size="tiny", language="zh")
        engine._model = mock_model  # inject directly

        segments = engine.transcribe(audio)

        assert len(segments) == 2
        assert segments[0].text == "hello"  # stripped
        assert segments[0].start == 0.0
        assert segments[0].end == 3.5
        assert segments[1].text == "world"
        assert segments[1].start == 3.5

    def test_transcribe_file_not_found(self):
        engine = WhisperEngine()
        engine._model = MagicMock()
        with pytest.raises(FileNotFoundError):
            engine.transcribe("/nonexistent/file.wav")

    def test_transcribe_passes_config(self, tmp_path: Path):
        audio = tmp_path / "test.wav"
        audio.write_bytes(b"RIFF" + b"\x00" * 100)

        mock_model = MagicMock()
        mock_info = MagicMock()
        mock_info.language = "en"
        mock_info.language_probability = 0.9
        mock_model.transcribe.return_value = (iter([]), mock_info)

        engine = WhisperEngine(
            model_size="small", language="en", beam_size=3, vad_filter=False
        )
        engine._model = mock_model

        engine.transcribe(audio)

        mock_model.transcribe.assert_called_once_with(
            str(audio),
            language="en",
            beam_size=3,
            vad_filter=False,
            vad_parameters=dict(min_silence_duration_ms=500),
            word_timestamps=False,
        )

    def test_is_loaded(self):
        engine = WhisperEngine()
        assert not engine.is_loaded
        engine._model = MagicMock()
        assert engine.is_loaded


# ── TaskState.has_transcript ────────────────────────────────


def test_has_transcript():
    from live2note.models.task import TaskState

    state = TaskState(task_id="test", url="https://example.com")
    assert not state.has_transcript(1)
    state.add_transcript(1, "transcripts/segment_001.json")
    assert state.has_transcript(1)
    assert not state.has_transcript(2)


# ── CLI transcribe command (mocked) ─────────────────────────


def _patch_base_dir(monkeypatch, tmp_path: Path) -> None:
    def factory():
        return tmp_path / "tasks"
    monkeypatch.setattr("live2note.paths.default_base_dir", factory)
    monkeypatch.setattr("live2note.config.default_base_dir", factory)


def test_transcribe_task_not_found(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from live2note.cli import app

    _patch_base_dir(monkeypatch, tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["transcribe", "nonexistent"])
    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_transcribe_no_segments(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from live2note.cli import app

    _patch_base_dir(monkeypatch, tmp_path)
    runner = CliRunner()

    # Create a task with no audio segments.
    runner.invoke(app, ["run", "https://example.com/live.m3u8", "--no-check", "--no-record"])
    tasks_dir = tmp_path / "tasks"
    task_id = next(tasks_dir.iterdir()).name

    result = runner.invoke(app, ["transcribe", task_id])
    assert result.exit_code == 1
    assert "No audio segments" in result.output


def test_transcribe_with_mocked_engine(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from live2note.cli import app

    _patch_base_dir(monkeypatch, tmp_path)
    runner = CliRunner()

    # Create a task and manually set up audio segments.
    runner.invoke(app, ["run", "https://example.com/live.m3u8", "--no-check", "--no-record"])
    tasks_dir = tmp_path / "tasks"
    task_id = next(tasks_dir.iterdir()).name

    # Create a fake audio segment file.
    task_dir = tasks_dir / task_id
    audio_dir = task_dir / "audio_segments"
    audio_dir.mkdir(parents=True, exist_ok=True)
    wav_path = audio_dir / "segment_001.wav"
    wav_path.write_bytes(b"RIFF" + b"\x00" * 100)

    # Update task state to reference the audio segment.
    state_file = task_dir / "task_state.json"
    data = json.loads(state_file.read_text(encoding="utf-8"))
    data["audio_segments"] = [
        {"index": 1, "file": str(wav_path), "duration": 5.0}
    ]
    state_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # Mock WhisperEngine (imported lazily inside the transcribe function).
    mock_segments = [
        Segment(start=0.0, end=2.5, text="test transcription", confidence=-0.1),
    ]

    with patch("live2note.transcriber.WhisperEngine") as MockEngine:
        instance = MockEngine.return_value
        instance.transcribe.return_value = mock_segments
        result = runner.invoke(app, ["transcribe", task_id])

    assert result.exit_code == 0
    assert "complete" in result.output.lower() or "done" in result.output.lower()

    # Verify output files exist.
    transcripts_dir = task_dir / "transcripts"
    assert (transcripts_dir / "segment_001.json").is_file()
    assert (transcripts_dir / "segment_001.md").is_file()

    # Verify JSON content.
    json_data = json.loads((transcripts_dir / "segment_001.json").read_text(encoding="utf-8"))
    assert json_data["segment_id"] == 1
    assert json_data["segments"][0]["text"] == "test transcription"
    assert json_data["segments"][0]["global_start"] == 0.0

    # Verify MD content.
    md_content = (transcripts_dir / "segment_001.md").read_text(encoding="utf-8")
    assert "test transcription" in md_content
    assert "[00:00]" in md_content

    # Verify task state updated.
    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert len(data["transcripts"]) == 1
    assert data["transcripts"][0]["index"] == 1


def test_transcribe_skips_already_done(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from live2note.cli import app

    _patch_base_dir(monkeypatch, tmp_path)
    runner = CliRunner()

    # Create task with audio segment.
    runner.invoke(app, ["run", "https://example.com/live.m3u8", "--no-check", "--no-record"])
    tasks_dir = tmp_path / "tasks"
    task_id = next(tasks_dir.iterdir()).name
    task_dir = tasks_dir / task_id

    audio_dir = task_dir / "audio_segments"
    audio_dir.mkdir(parents=True, exist_ok=True)
    wav = audio_dir / "segment_001.wav"
    wav.write_bytes(b"RIFF" + b"\x00" * 100)

    # Pre-populate transcripts in task state.
    state_file = task_dir / "task_state.json"
    data = json.loads(state_file.read_text(encoding="utf-8"))
    data["audio_segments"] = [{"index": 1, "file": str(wav), "duration": 5.0}]
    data["transcripts"] = [{"index": 1, "file": "transcripts/segment_001.json"}]
    state_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # Write existing transcript files.
    transcripts_dir = task_dir / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    (transcripts_dir / "segment_001.json").write_text("{}", encoding="utf-8")

    with patch("live2note.transcriber.WhisperEngine") as MockEngine:
        instance = MockEngine.return_value
        result = runner.invoke(app, ["transcribe", task_id])

    assert result.exit_code == 0
    instance.transcribe.assert_not_called()
    assert "already transcribed" in result.output.lower() or "skipped" in result.output.lower()
