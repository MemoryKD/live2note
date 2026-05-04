"""Tests for final note builder, markdown writer, json writer, and save CLI."""

from __future__ import annotations

import json
from pathlib import Path

from live2note.processor.final_note_builder import build_final_note
from live2note.storage.json_writer import write_final_json
from live2note.storage.markdown_writer import write_final_markdown

# ── Fixtures ────────────────────────────────────────────────

def _sample_metadata() -> dict:
    return {
        "platform": "bilibili",
        "room_id": "12345",
        "streamer": "知识分享官",
        "title": "AI 入门系列第三讲",
        "started_at": "2026-05-04T14:00:00+08:00",
        "ended_at": "2026-05-04T15:00:00+08:00",
        "url": "https://live.bilibili.com/12345",
        "stream_url": "https://pull.bilibili.com/stream.flv",
    }


def _sample_chunks() -> list[dict]:
    return [
        {
            "chunk_id": 1,
            "start": 0.0,
            "end": 60.0,
            "text": "今天讲人工智能基础。机器学习是AI的子集。",
            "source_segments": [{"start": 0.0, "end": 30.0}, {"start": 30.0, "end": 60.0}],
        },
        {
            "chunk_id": 2,
            "start": 60.0,
            "end": 120.0,
            "text": "深度学习使用多层神经网络。CNN适合图像处理。",
            "source_segments": [{"start": 60.0, "end": 120.0}],
        },
    ]


def _sample_summaries() -> list[dict]:
    return [
        {
            "chunk_id": 1,
            "start": 0.0,
            "end": 60.0,
            "summary": "介绍了人工智能的基本概念和机器学习的定义。",
            "key_points": ["机器学习是AI的子集", "AI让计算机模拟人类智能"],
            "knowledge_points": ["AI = Artificial Intelligence", "ML = Machine Learning"],
            "action_items": ["阅读《机器学习》周志华"],
            "tags": ["AI", "机器学习"],
            "keywords": ["人工智能", "机器学习", "计算机科学"],
            "important_quotes": ["机器学习是AI的子集"],
        },
        {
            "chunk_id": 2,
            "start": 60.0,
            "end": 120.0,
            "summary": "讲解了深度学习和CNN的基本概念。",
            "key_points": ["深度学习是机器学习的分支", "CNN适合图像处理"],
            "knowledge_points": ["CNN = Convolutional Neural Network", "神经网络灵感来自人脑"],
            "action_items": ["学习PyTorch基础"],
            "tags": ["深度学习", "CNN"],
            "keywords": ["深度学习", "神经网络", "CNN"],
            "important_quotes": ["CNN适合图像处理"],
        },
    ]


# ── build_final_note ────────────────────────────────────────


def test_build_with_summaries():
    note = build_final_note("task_001", _sample_metadata(), _sample_chunks(), _sample_summaries())
    assert note.task_id == "task_001"
    assert note.platform == "bilibili"
    assert note.streamer == "知识分享官"
    assert note.stream_title == "AI 入门系列第三讲"
    assert note.source_url == "https://live.bilibili.com/12345"
    assert note.started_at == "2026-05-04T14:00:00+08:00"
    assert len(note.key_points) == 4
    assert len(note.action_items) == 2
    assert len(note.tags) >= 2
    assert len(note.keywords) >= 3
    assert len(note.important_quotes) == 2
    assert len(note.timestamp_index) == 2
    assert "LLM" not in note.one_line_summary  # summaries present


def test_build_without_summaries():
    note = build_final_note("task_002", _sample_metadata(), _sample_chunks(), None)
    assert note.one_line_summary == "未进行 LLM 总结"
    assert note.key_points == ["未进行 LLM 总结"]
    assert note.action_items == ["未进行 LLM 总结"]
    assert note.follow_up_questions == ["未进行 LLM 总结，无法生成追问问题"]


def test_build_empty_chunks():
    note = build_final_note("task_003", _sample_metadata(), [], None)
    assert note.one_line_summary == "未进行 LLM 总结"
    assert len(note.timestamp_index) == 0


def test_build_title_from_metadata():
    note = build_final_note("t1", _sample_metadata(), [], None)
    assert note.title == "AI 入门系列第三讲"


def test_build_title_fallback():
    note = build_final_note("t1", {"platform": "generic"}, [], None)
    assert "t1" in note.title


def test_build_deduplication():
    """Key points, tags, keywords should be deduplicated."""
    summaries = [
        {"chunk_id": 1, "start": 0, "end": 10, "summary": "s",
         "key_points": ["A", "B"], "knowledge_points": [], "action_items": [],
         "tags": ["T1"], "keywords": ["K1"], "important_quotes": []},
        {"chunk_id": 2, "start": 10, "end": 20, "summary": "s",
         "key_points": ["A", "C"], "knowledge_points": [], "action_items": [],
         "tags": ["T1", "T2"], "keywords": ["K1", "K2"], "important_quotes": []},
    ]
    chunks = [
        {"chunk_id": 1, "start": 0, "end": 10, "text": "x", "source_segments": []},
        {"chunk_id": 2, "start": 10, "end": 20, "text": "y", "source_segments": []},
    ]
    note = build_final_note("t", {"platform": "p"}, chunks, summaries)
    assert note.key_points == ["A", "B", "C"]
    assert note.tags == ["T1", "T2"]
    assert note.keywords == ["K1", "K2"]


# ── write_final_markdown ────────────────────────────────────


def test_write_markdown_contains_all_sections(tmp_path: Path):
    note = build_final_note("task_md", _sample_metadata(), _sample_chunks(), _sample_summaries())
    out = tmp_path / "final_note.md"
    write_final_markdown(note, out)

    content = out.read_text(encoding="utf-8")

    # All required sections.
    assert "# AI 入门系列第三讲" in content
    assert "## 基本信息" in content
    assert "平台：bilibili" in content
    assert "主播：知识分享官" in content
    assert "来源链接：https://live.bilibili.com/12345" in content
    assert "任务 ID：task_md" in content
    assert "## 一句话总结" in content
    assert "## 核心观点" in content
    assert "## 主题化知识整理" in content
    assert "## 可执行建议" in content
    assert "## 重要观点索引" in content
    assert "## 原文重要片段" in content
    assert "## 检索关键词" in content
    assert "## 时间戳索引" in content
    assert "## 后续可追问的问题" in content


def test_write_markdown_has_timestamps(tmp_path: Path):
    note = build_final_note("t", _sample_metadata(), _sample_chunks(), _sample_summaries())
    out = tmp_path / "note.md"
    write_final_markdown(note, out)
    content = out.read_text(encoding="utf-8")
    assert "[00:00" in content
    assert "[01:00" in content


def test_write_markdown_no_summaries(tmp_path: Path):
    note = build_final_note("t", _sample_metadata(), _sample_chunks(), None)
    out = tmp_path / "note.md"
    write_final_markdown(note, out)
    content = out.read_text(encoding="utf-8")
    assert "未进行 LLM 总结" in content


def test_write_markdown_creates_parent_dirs(tmp_path: Path):
    note = build_final_note("t", {}, [], None)
    out = tmp_path / "deep" / "nested" / "note.md"
    write_final_markdown(note, out)
    assert out.is_file()


# ── write_final_json ────────────────────────────────────────


def test_write_json_roundtrip(tmp_path: Path):
    note = build_final_note("task_json", _sample_metadata(), _sample_chunks(), _sample_summaries())
    out = tmp_path / "final_note.json"
    write_final_json(note, out)

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["task_id"] == "task_json"
    assert data["platform"] == "bilibili"
    assert data["streamer"] == "知识分享官"
    assert data["source_url"] == "https://live.bilibili.com/12345"
    assert data["started_at"] == "2026-05-04T14:00:00+08:00"
    assert len(data["key_points"]) == 4
    assert len(data["timestamp_index"]) == 2
    assert "knowledge_sections" in data
    assert "follow_up_questions" in data


def test_write_json_no_summaries(tmp_path: Path):
    note = build_final_note("t", {}, [], None)
    out = tmp_path / "note.json"
    write_final_json(note, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["one_line_summary"] == "未进行 LLM 总结"


# ── CLI save command ────────────────────────────────────────


def _patch_base_dir(monkeypatch, tmp_path: Path) -> None:
    def factory():
        return tmp_path / "tasks"
    monkeypatch.setattr("live2note.paths.default_base_dir", factory)
    monkeypatch.setattr("live2note.config.default_base_dir", factory)


def _create_task_with_chunks(tmp_path, runner, monkeypatch):
    """Create a task with chunks and summaries for save testing."""
    from live2note.cli import app

    _patch_base_dir(monkeypatch, tmp_path)
    result = runner.invoke(app, ["run", "https://example.com/live.m3u8", "--no-check", "--no-record"])
    tasks_dir = tmp_path / "tasks"
    assert tasks_dir.is_dir(), f"run failed: {result.output}"
    task_id = next(tasks_dir.iterdir()).name
    task_dir = tasks_dir / task_id

    # Write chunks.
    chunks_dir = task_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    (chunks_dir / "chunks.json").write_text(
        json.dumps(_sample_chunks(), indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Write summaries.
    summaries_dir = task_dir / "summaries"
    summaries_dir.mkdir(parents=True, exist_ok=True)
    (summaries_dir / "chunk_summaries.json").write_text(
        json.dumps(_sample_summaries(), indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Update task metadata.
    state_file = task_dir / "task_state.json"
    data = json.loads(state_file.read_text(encoding="utf-8"))
    data["metadata"]["platform"] = "bilibili"
    data["metadata"]["streamer"] = "知识分享官"
    data["metadata"]["title"] = "AI 入门系列第三讲"
    data["metadata"]["url"] = "https://live.bilibili.com/12345"
    data["finished_steps"] = ["check", "record", "transcribe", "process", "summarize"]
    state_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    return task_id, task_dir


def test_save_creates_files(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from live2note.cli import app

    runner = CliRunner()
    task_id, task_dir = _create_task_with_chunks(tmp_path, runner, monkeypatch)

    result = runner.invoke(app, ["save", task_id])
    assert result.exit_code == 0
    assert "Final note generated" in result.output

    md_path = task_dir / "notes" / "final_note.md"
    json_path = task_dir / "notes" / "final_note.json"
    assert md_path.is_file()
    assert json_path.is_file()

    # Verify MD structure.
    md = md_path.read_text(encoding="utf-8")
    assert "# AI 入门系列第三讲" in md
    assert "## 基本信息" in md
    assert "## 核心观点" in md
    assert "## 检索关键词" in md

    # Verify JSON structure.
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["task_id"] == task_id
    assert data["platform"] == "bilibili"


def test_save_updates_task_state(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from live2note.cli import app

    runner = CliRunner()
    task_id, task_dir = _create_task_with_chunks(tmp_path, runner, monkeypatch)

    runner.invoke(app, ["save", task_id])

    state_file = task_dir / "task_state.json"
    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert data["final_note_path"] is not None
    assert "save" in data["finished_steps"]


def test_save_without_summaries(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from live2note.cli import app

    runner = CliRunner()
    _patch_base_dir(monkeypatch, tmp_path)
    result = runner.invoke(app, ["run", "https://example.com/live.m3u8", "--no-check", "--no-record"])
    tasks_dir = tmp_path / "tasks"
    task_id = next(tasks_dir.iterdir()).name
    task_dir = tasks_dir / task_id

    # Write chunks only (no summaries).
    chunks_dir = task_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    (chunks_dir / "chunks.json").write_text(
        json.dumps(_sample_chunks(), indent=2, ensure_ascii=False), encoding="utf-8"
    )

    result = runner.invoke(app, ["save", task_id])
    assert result.exit_code == 0

    md = (task_dir / "notes" / "final_note.md").read_text(encoding="utf-8")
    assert "未进行 LLM 总结" in md


def test_save_not_found(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from live2note.cli import app

    runner = CliRunner()
    _patch_base_dir(monkeypatch, tmp_path)
    result = runner.invoke(app, ["save", "nonexistent"])
    assert result.exit_code == 1


def test_save_no_chunks(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from live2note.cli import app

    runner = CliRunner()
    _patch_base_dir(monkeypatch, tmp_path)
    result = runner.invoke(app, ["run", "https://example.com/live.m3u8", "--no-check", "--no-record"])
    tasks_dir = tmp_path / "tasks"
    task_id = next(tasks_dir.iterdir()).name

    result = runner.invoke(app, ["save", task_id])
    assert result.exit_code == 0
    assert "No chunks" in result.output
