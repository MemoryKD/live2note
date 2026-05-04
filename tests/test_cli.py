"""CLI smoke tests."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from live2note.cli import app

runner = CliRunner()


def _patch_base_dir(monkeypatch, tmp_path: Path) -> None:
    """Patch default_base_dir in all modules that import it."""
    def factory():
        return tmp_path / "tasks"
    monkeypatch.setattr("live2note.paths.default_base_dir", factory)
    monkeypatch.setattr("live2note.config.default_base_dir", factory)


# All run invocations use --no-check --no-record to avoid subprocess calls.


def test_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "live2note" in result.output.lower()


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "0.1.1" in result.output


def test_config_init(tmp_path: Path):
    target = tmp_path / "config.yaml"
    result = runner.invoke(app, ["config-init", str(target)])
    assert result.exit_code == 0
    assert target.is_file()


def test_run_creates_task(tmp_path: Path, monkeypatch):
    _patch_base_dir(monkeypatch, tmp_path)
    result = runner.invoke(
        app, ["run", "https://live.bilibili.com/12345", "--no-check", "--no-record"]
    )
    assert result.exit_code == 0
    assert "Task created" in result.output
    assert "bilibili" in result.output

    state_files = list((tmp_path / "tasks").rglob("task_state.json"))
    assert len(state_files) == 1
    meta_files = list((tmp_path / "tasks").rglob("metadata.json"))
    assert len(meta_files) == 1


def test_run_with_options(tmp_path: Path, monkeypatch):
    _patch_base_dir(monkeypatch, tmp_path)
    result = runner.invoke(
        app,
        [
            "run",
            "https://live.bilibili.com/1",
            "--duration", "30",
            "--getnote",
            "--getnote-tag", "test",
            "--no-check",
            "--no-record",
        ],
    )
    assert result.exit_code == 0
    state_files = list((tmp_path / "tasks").rglob("task_state.json"))
    assert len(state_files) == 1
    data = json.loads(state_files[0].read_text(encoding="utf-8"))
    assert data["duration"] == 30
    assert data["getnote_tags"] == ["test"]


def test_run_stream_url_option(tmp_path: Path, monkeypatch):
    _patch_base_dir(monkeypatch, tmp_path)
    result = runner.invoke(
        app,
        [
            "run",
            "https://example.com/page",
            "--platform", "generic",
            "--stream-url", "https://cdn.com/live.m3u8",
            "--no-check",
            "--no-record",
        ],
    )
    assert result.exit_code == 0
    assert "Task created" in result.output


def test_status_no_tasks(tmp_path: Path, monkeypatch):
    _patch_base_dir(monkeypatch, tmp_path)
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "No tasks" in result.output


def test_status_shows_task(tmp_path: Path, monkeypatch):
    _patch_base_dir(monkeypatch, tmp_path)
    runner.invoke(
        app, ["run", "https://example.com/live.m3u8", "--no-check", "--no-record"]
    )
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "CREATED" in result.output
    assert "Pipeline" in result.output


def test_status_by_id(tmp_path: Path, monkeypatch):
    _patch_base_dir(monkeypatch, tmp_path)
    runner.invoke(
        app, ["run", "https://example.com/live.m3u8", "--no-check", "--no-record"]
    )
    tasks_dir = tmp_path / "tasks"
    task_id = next(tasks_dir.iterdir()).name
    result = runner.invoke(app, ["status", task_id])
    assert result.exit_code == 0
    assert "CREATED" in result.output


def test_status_not_found(tmp_path: Path, monkeypatch):
    _patch_base_dir(monkeypatch, tmp_path)
    result = runner.invoke(app, ["status", "nonexistent"])
    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_list_no_tasks(tmp_path: Path, monkeypatch):
    _patch_base_dir(monkeypatch, tmp_path)
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "No tasks" in result.output


def test_list_shows_tasks(tmp_path: Path, monkeypatch):
    _patch_base_dir(monkeypatch, tmp_path)
    runner.invoke(
        app, ["run", "https://live.bilibili.com/1", "--no-check", "--no-record"]
    )
    runner.invoke(
        app, ["run", "https://live.douyin.com/2", "--no-check", "--no-record"]
    )
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "bilibili" in result.output
    assert "douyin" in result.output


def test_resume_not_found(tmp_path: Path, monkeypatch):
    _patch_base_dir(monkeypatch, tmp_path)
    result = runner.invoke(app, ["resume", "nonexistent"])
    assert result.exit_code == 1


def test_resume_shows_status(tmp_path: Path, monkeypatch):
    _patch_base_dir(monkeypatch, tmp_path)
    runner.invoke(
        app, ["run", "https://example.com/live.m3u8", "--no-check", "--no-record"]
    )
    tasks_dir = tmp_path / "tasks"
    task_id = next(tasks_dir.iterdir()).name
    result = runner.invoke(app, ["resume", task_id])
    assert result.exit_code == 0
    assert "resumed" in result.output.lower()
    assert "check" in result.output
