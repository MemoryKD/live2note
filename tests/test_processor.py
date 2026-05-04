"""Tests for cleaner, chunker, summarizer, and process CLI command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from live2note.processor.chunker import Chunk, chunk_segments
from live2note.processor.cleaner import CleanSegment, clean_segments
from live2note.processor.summarizer import ChunkSummary, Summarizer

# ── cleaner ─────────────────────────────────────────────────


def test_clean_removes_filler():
    segs = [
        CleanSegment(0.0, 3.0, "嗯，这个我想说一下"),
        CleanSegment(3.0, 6.0, "啊，然后呢就是这个样子"),
    ]
    result = clean_segments(segs)
    assert len(result) == 2
    assert "嗯" not in result[0].text
    assert "啊" not in result[1].text
    assert "然后呢" not in result[1].text


def test_clean_removes_duplicate_consecutive():
    segs = [
        CleanSegment(0.0, 3.0, "今天讲一下 AI 的基础知识。"),
        CleanSegment(3.0, 6.0, "今天讲一下 AI 的基础知识。"),
        CleanSegment(6.0, 9.0, "首先什么是机器学习。"),
    ]
    result = clean_segments(segs)
    assert len(result) == 2
    # Duplicate merged into first segment's time range.
    assert result[0].end == 6.0
    assert result[0].text == "今天讲一下 AI 的基础知识。"


def test_clean_collapses_multi_punctuation():
    segs = [CleanSegment(0.0, 3.0, "真的吗！！！太好了。。。")]
    result = clean_segments(segs)
    assert "！！" not in result[0].text
    assert "。。" not in result[0].text


def test_clean_drops_empty():
    segs = [
        CleanSegment(0.0, 1.0, ""),
        CleanSegment(1.0, 2.0, "嗯"),
        CleanSegment(2.0, 3.0, "实际内容"),
    ]
    result = clean_segments(segs)
    assert len(result) >= 1
    assert any("实际内容" in s.text for s in result)


def test_clean_preserves_timestamps():
    segs = [
        CleanSegment(10.5, 15.2, "有效内容一"),
        CleanSegment(15.2, 20.0, "有效内容二"),
    ]
    result = clean_segments(segs)
    assert result[0].start == 10.5
    assert result[0].end == 15.2
    assert result[1].start == 15.2


# ── chunker ─────────────────────────────────────────────────


def test_chunk_single_short_text():
    segs = [CleanSegment(0.0, 10.0, "短文本")]
    chunks = chunk_segments(segs, min_chars=100, max_chars=500)
    assert len(chunks) == 1
    assert chunks[0].chunk_id == 1
    assert chunks[0].text == "短文本"
    assert chunks[0].start == 0.0
    assert chunks[0].end == 10.0
    assert len(chunks[0].source_segments) == 1


def test_chunk_respects_max_chars():
    segs = [
        CleanSegment(float(i * 10), float((i + 1) * 10), f"段落{i}。" * 50)
        for i in range(10)
    ]
    chunks = chunk_segments(segs, min_chars=100, max_chars=300)
    for c in chunks:
        assert len(c.text) <= 300 + 200  # allow overshoot from one segment


def test_chunk_preserves_order():
    segs = [CleanSegment(float(i), float(i + 1), f"text{i}。") for i in range(20)]
    chunks = chunk_segments(segs, min_chars=10, max_chars=50)
    for i, c in enumerate(chunks):
        assert c.chunk_id == i + 1
    # Start times should be monotonically increasing.
    for i in range(1, len(chunks)):
        assert chunks[i].start >= chunks[i - 1].start


def test_chunk_source_segments_tracked():
    segs = [
        CleanSegment(0.0, 5.0, "A" * 200),
        CleanSegment(5.0, 10.0, "B" * 200),
        CleanSegment(10.0, 15.0, "C" * 200),
    ]
    chunks = chunk_segments(segs, min_chars=100, max_chars=500)
    # All three segments should appear in source_segments.
    all_sources = []
    for c in chunks:
        all_sources.extend(c.source_segments)
    assert len(all_sources) == 3


def test_chunk_empty_input():
    assert chunk_segments([]) == []


# ── summarizer ──────────────────────────────────────────────


class _MockProvider:
    """A mock LLM provider for testing."""
    def __init__(self, available=True, response="{}"):
        self._available = available
        self._response = response
        self.name = "mock"

    def generate(self, prompt, **kwargs):
        from live2note.llm.base import LLMResult
        return LLMResult(text=self._response)

    @property
    def is_available(self):
        return self._available


class TestSummarizer:
    def test_is_configured(self):
        s = Summarizer(provider=_MockProvider(available=True))
        assert s.is_configured
        s2 = Summarizer(provider=_MockProvider(available=False))
        assert not s2.is_configured

    def test_parse_json_response(self):
        raw = json.dumps({
            "summary": "Test summary",
            "key_points": ["Point 1"],
            "knowledge_points": [],
            "action_items": [],
            "tags": ["test"],
            "keywords": ["keyword"],
            "important_quotes": [],
        })
        result = Summarizer._parse_response(raw)
        assert result["summary"] == "Test summary"
        assert result["key_points"] == ["Point 1"]

    def test_parse_fenced_json(self):
        raw = '```json\n{"summary": "OK", "key_points": []}\n```'
        result = Summarizer._parse_response(raw)
        assert result["summary"] == "OK"

    def test_parse_invalid_json_fallback(self):
        raw = "This is not JSON at all."
        result = Summarizer._parse_response(raw)
        assert "This is not JSON" in result["summary"]
        assert result["key_points"] == []

    def test_summarize_returns_chunk_summary(self):
        mock_response = json.dumps({
            "summary": "AI basics explained",
            "key_points": ["ML is a subset of AI"],
            "knowledge_points": ["Neural networks mimic brain"],
            "action_items": ["Read chapter 1"],
            "tags": ["AI", "ML"],
            "keywords": ["neural", "network"],
            "important_quotes": ["AI is the future"],
        })
        s = Summarizer(provider=_MockProvider(response=mock_response))
        chunk = Chunk(chunk_id=1, start=0.0, end=60.0, text="AI basics...")
        result = s.summarize(chunk)

        assert isinstance(result, ChunkSummary)
        assert result.chunk_id == 1
        assert result.summary == "AI basics explained"
        assert result.start == 0.0
        assert result.end == 60.0
        assert len(result.key_points) == 1
        assert "AI" in result.tags


# ── CLI process command ─────────────────────────────────────


def _patch_base_dir(monkeypatch, tmp_path: Path) -> None:
    def factory():
        return tmp_path / "tasks"
    monkeypatch.setattr("live2note.paths.default_base_dir", factory)
    monkeypatch.setattr("live2note.config.default_base_dir", factory)


def _create_task_with_transcripts(tmp_path, runner, monkeypatch):
    """Create a task with transcript files, return (task_id, task_dir)."""
    _patch_base_dir(monkeypatch, tmp_path)
    result = runner.invoke(
        live2note_app(), ["run", "https://example.com/live.m3u8", "--no-check", "--no-record"]
    )
    tasks_dir = tmp_path / "tasks"
    assert tasks_dir.is_dir(), f"Task creation failed: {result.output}"
    task_id = next(tasks_dir.iterdir()).name
    task_dir = tasks_dir / task_id

    # Create transcript files.
    transcripts_dir = task_dir / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)

    transcript = {
        "segment_id": 1,
        "audio_file": "segment_001.wav",
        "global_offset": 0.0,
        "segment_count": 3,
        "segments": [
            {"start": 0.0, "end": 5.0, "global_start": 0.0, "global_end": 5.0,
             "text": "今天我想和大家聊一聊人工智能的基础知识。人工智能是计算机科学的一个分支。", "confidence": -0.1},
            {"start": 5.0, "end": 10.0, "global_start": 5.0, "global_end": 10.0,
             "text": "它试图让计算机模拟人类的智能行为。机器学习是人工智能的一个子集。", "confidence": -0.15},
            {"start": 10.0, "end": 15.0, "global_start": 10.0, "global_end": 15.0,
             "text": "深度学习又是机器学习的一个分支。神经网络是深度学习的核心技术。", "confidence": -0.12},
        ],
    }
    (transcripts_dir / "segment_001.json").write_text(
        json.dumps(transcript, ensure_ascii=False), encoding="utf-8"
    )

    # Update task state with transcript reference.
    state_file = task_dir / "task_state.json"
    data = json.loads(state_file.read_text(encoding="utf-8"))
    data["transcripts"] = [{"index": 1, "file": str(transcripts_dir / "segment_001.json")}]
    data["finished_steps"] = ["check", "record", "transcribe"]
    state_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    return task_id, task_dir


def live2note_app():
    from live2note.cli import app
    return app


def test_process_no_transcripts(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner
    runner = CliRunner()
    _patch_base_dir(monkeypatch, tmp_path)
    result = runner.invoke(live2note_app(), ["run", "https://example.com", "--platform", "generic", "--no-check", "--no-record"])
    tasks_dir = tmp_path / "tasks"
    assert tasks_dir.is_dir(), f"run failed: {result.output}"
    task_id = next(tasks_dir.iterdir()).name
    result = runner.invoke(live2note_app(), ["process", task_id])
    assert result.exit_code == 1
    assert "No transcript" in result.output


def test_process_skip_llm(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner
    runner = CliRunner()
    task_id, task_dir = _create_task_with_transcripts(tmp_path, runner, monkeypatch)

    result = runner.invoke(live2note_app(), ["process", task_id, "--skip-llm"])
    assert result.exit_code == 0
    assert "Chunks saved" in result.output
    assert "skipped" in result.output.lower()

    # Verify chunks.json exists.
    chunks_path = task_dir / "chunks" / "chunks.json"
    assert chunks_path.is_file()
    chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
    assert len(chunks) >= 1
    assert chunks[0]["chunk_id"] == 1
    assert "start" in chunks[0]
    assert "end" in chunks[0]
    assert "text" in chunks[0]
    assert "source_segments" in chunks[0]


def test_process_no_api_key_shows_hint(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner
    runner = CliRunner()
    task_id, _ = _create_task_with_transcripts(tmp_path, runner, monkeypatch)

    # Ensure no API key.
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    result = runner.invoke(live2note_app(), ["process", task_id])
    # Without API key, the process command still completes by generating chunks
    # and final note (prompt_only fallback).
    assert result.exit_code == 0
    assert "Chunks saved" in result.output


def test_process_with_mocked_llm(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner
    runner = CliRunner()
    task_id, task_dir = _create_task_with_transcripts(tmp_path, runner, monkeypatch)

    mock_summary = json.dumps({
        "summary": "AI basics overview",
        "key_points": ["ML is subset of AI"],
        "knowledge_points": ["Neural networks"],
        "action_items": ["Study more"],
        "tags": ["AI"],
        "keywords": ["machine learning"],
        "important_quotes": ["AI is the future"],
    })

    from live2note.llm.base import LLMResult

    # Set API key and mock the provider's generate method.
    with (
        patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}),
        patch("live2note.llm.openai_compatible.OpenAICompatibleProvider.generate",
              return_value=LLMResult(text=mock_summary)),
    ):
        result = runner.invoke(
            live2note_app(),
            ["process", task_id, "--provider", "openai_compatible"],
        )

    assert result.exit_code == 0
    assert "Summaries saved" in result.output

    # Verify chunk_summaries.json.
    summaries_path = task_dir / "summaries" / "chunk_summaries.json"
    assert summaries_path.is_file()
    summaries = json.loads(summaries_path.read_text(encoding="utf-8"))
    assert len(summaries) >= 1
    assert summaries[0]["summary"] == "AI basics overview"
    assert summaries[0]["tags"] == ["AI"]
    assert summaries[0]["keywords"] == ["machine learning"]


def test_process_not_found(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner
    runner = CliRunner()
    _patch_base_dir(monkeypatch, tmp_path)
    result = runner.invoke(live2note_app(), ["process", "nonexistent"])
    assert result.exit_code == 1
