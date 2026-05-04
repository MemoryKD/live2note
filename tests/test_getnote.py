"""Tests for getnote integration."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from live2note.models.task import TaskState
from live2note.storage.getnote import GetnoteResult, import_to_getnote

# ── import_to_getnote ───────────────────────────────────────


def test_file_not_found():
    result = import_to_getnote("/nonexistent/file.md")
    assert not result.success
    assert "not found" in result.message.lower()


def test_success(tmp_path: Path):
    md = tmp_path / "note.md"
    md.write_text("# Test", encoding="utf-8")

    mock_run_result = type("R", (), {"returncode": 0, "stdout": "OK saved", "stderr": ""})()
    with patch("live2note.storage.getnote.subprocess.run", return_value=mock_run_result):
        result = import_to_getnote(md, command_template='getnote save "{file_path}"')

    assert result.success
    assert "success" in result.message.lower()
    assert result.stdout == "OK saved"


def test_failure_nonzero_exit(tmp_path: Path):
    md = tmp_path / "note.md"
    md.write_text("# Test", encoding="utf-8")

    mock_run_result = type("R", (), {"returncode": 1, "stdout": "", "stderr": "auth error"})()
    with patch("live2note.storage.getnote.subprocess.run", return_value=mock_run_result):
        result = import_to_getnote(md)

    assert not result.success
    assert "code 1" in result.message
    assert result.stderr == "auth error"


def test_timeout(tmp_path: Path):
    import subprocess

    md = tmp_path / "note.md"
    md.write_text("# Test", encoding="utf-8")

    with patch(
        "live2note.storage.getnote.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="getnote", timeout=5),
    ):
        result = import_to_getnote(md, timeout=5)

    assert not result.success
    assert "timed out" in result.message.lower()


def test_command_not_found(tmp_path: Path):
    md = tmp_path / "note.md"
    md.write_text("# Test", encoding="utf-8")

    with patch(
        "live2note.storage.getnote.subprocess.run",
        side_effect=FileNotFoundError,
    ):
        result = import_to_getnote(md)

    assert not result.success
    assert "not found" in result.message.lower()


def test_template_substitution(tmp_path: Path):
    md = tmp_path / "note.md"
    md.write_text("# Test", encoding="utf-8")

    captured_cmd = {}

    def fake_run(cmd, **kwargs):
        captured_cmd["cmd"] = cmd
        return type("R", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

    with patch("live2note.storage.getnote.subprocess.run", side_effect=fake_run):
        import_to_getnote(
            md,
            command_template='getnote save "{file_path}" --title "{title}"',
            title="My Title",
            tags=["tag1", "tag2"],
        )

    assert str(md) in captured_cmd["cmd"]
    assert "My Title" in captured_cmd["cmd"]
    assert "--tag" in captured_cmd["cmd"]


def test_default_title_from_filename(tmp_path: Path):
    md = tmp_path / "my_note.md"
    md.write_text("# Test", encoding="utf-8")

    captured_cmd = {}

    def fake_run(cmd, **kwargs):
        captured_cmd["cmd"] = cmd
        return type("R", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

    with patch("live2note.storage.getnote.subprocess.run", side_effect=fake_run):
        import_to_getnote(md, command_template='getnote save "{file_path}" --title "{title}"')

    assert "my_note" in captured_cmd["cmd"]


# ── TaskState getnote fields ────────────────────────────────


def test_task_state_getnote_fields():
    state = TaskState(task_id="t", url="u")
    assert state.getnote_enabled is False
    assert state.getnote_imported is False
    assert state.getnote_import_time is None
    assert state.getnote_error is None


def test_task_state_getnote_serialization():
    state = TaskState(task_id="t", url="u", getnote_enabled=True)
    state.getnote_imported = True
    state.getnote_import_time = "2026-05-04T12:00:00Z"
    state.getnote_error = None
    d = state.to_dict()
    assert d["getnote_enabled"] is True
    assert d["getnote_imported"] is True
    assert d["getnote_import_time"] == "2026-05-04T12:00:00Z"
    assert d["getnote_error"] is None

    restored = TaskState.from_dict(d)
    assert restored.getnote_enabled is True
    assert restored.getnote_imported is True
    assert restored.getnote_import_time == "2026-05-04T12:00:00Z"


def test_task_state_getnote_backward_compat():
    """Old task_state.json without getnote_enabled should default to False."""
    data = {"task_id": "t", "url": "u"}
    state = TaskState.from_dict(data)
    assert state.getnote_enabled is False
    assert state.getnote_import_time is None
    assert state.getnote_error is None


# ── CLI import-getnote ──────────────────────────────────────


def _patch_base_dir(monkeypatch, tmp_path: Path) -> None:
    def factory():
        return tmp_path / "tasks"
    monkeypatch.setattr("live2note.paths.default_base_dir", factory)
    monkeypatch.setattr("live2note.config.default_base_dir", factory)


def test_import_getnote_no_note(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from live2note.cli import app

    _patch_base_dir(monkeypatch, tmp_path)
    runner = CliRunner()
    runner.invoke(app, ["run", "https://example.com/live.m3u8", "--no-check", "--no-record"])
    task_id = next((tmp_path / "tasks").iterdir()).name

    result = runner.invoke(app, ["import-getnote", task_id])
    assert result.exit_code == 0
    assert "No final note" in result.output


def test_import_getnote_success(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from live2note.cli import app

    _patch_base_dir(monkeypatch, tmp_path)
    runner = CliRunner()
    runner.invoke(app, ["run", "https://example.com/live.m3u8", "--no-check", "--no-record"])
    task_id = next((tmp_path / "tasks").iterdir()).name
    task_dir = tmp_path / "tasks" / task_id

    # Create final_note.md.
    notes_dir = task_dir / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    (notes_dir / "final_note.md").write_text("# Test Note", encoding="utf-8")

    # Update task state with final_note_path.
    state_file = task_dir / "task_state.json"
    data = json.loads(state_file.read_text(encoding="utf-8"))
    data["final_note_path"] = str(notes_dir / "final_note.md")
    state_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    mock_result = GetnoteResult(success=True, message="OK", stdout="saved")
    with patch("live2note.storage.getnote.import_to_getnote", return_value=mock_result):
        result = runner.invoke(app, ["import-getnote", task_id])

    assert result.exit_code == 0
    assert "succeeded" in result.output.lower()

    # Verify task state updated.
    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert data["getnote_imported"] is True
    assert data["getnote_import_time"] is not None
    assert data["getnote_error"] is None


def test_import_getnote_failure_does_not_break(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from live2note.cli import app

    _patch_base_dir(monkeypatch, tmp_path)
    runner = CliRunner()
    runner.invoke(app, ["run", "https://example.com/live.m3u8", "--no-check", "--no-record"])
    task_id = next((tmp_path / "tasks").iterdir()).name
    task_dir = tmp_path / "tasks" / task_id

    notes_dir = task_dir / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    (notes_dir / "final_note.md").write_text("# Test", encoding="utf-8")

    state_file = task_dir / "task_state.json"
    data = json.loads(state_file.read_text(encoding="utf-8"))
    data["final_note_path"] = str(notes_dir / "final_note.md")
    state_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    mock_result = GetnoteResult(success=False, message="auth failed", stderr="401")
    with patch("live2note.storage.getnote.import_to_getnote", return_value=mock_result):
        result = runner.invoke(app, ["import-getnote", task_id])

    assert result.exit_code == 0  # does NOT fail the CLI
    assert "failed" in result.output.lower()

    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert data["getnote_imported"] is False
    assert data["getnote_error"] == "auth failed"
    # File still exists.
    assert (notes_dir / "final_note.md").is_file()


def test_import_getnote_already_imported(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from live2note.cli import app

    _patch_base_dir(monkeypatch, tmp_path)
    runner = CliRunner()
    runner.invoke(app, ["run", "https://example.com/live.m3u8", "--no-check", "--no-record"])
    task_id = next((tmp_path / "tasks").iterdir()).name
    task_dir = tmp_path / "tasks" / task_id

    notes_dir = task_dir / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    (notes_dir / "final_note.md").write_text("# Test", encoding="utf-8")

    state_file = task_dir / "task_state.json"
    data = json.loads(state_file.read_text(encoding="utf-8"))
    data["final_note_path"] = str(notes_dir / "final_note.md")
    data["getnote_imported"] = True
    state_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    mock_result = GetnoteResult(success=True, message="OK")
    with patch("live2note.storage.getnote.import_to_getnote", return_value=mock_result) as mock_fn:
        result = runner.invoke(app, ["import-getnote", task_id])

    assert result.exit_code == 0
    assert "already imported" in result.output.lower()
    mock_fn.assert_not_called()


def test_import_getnote_force_reimport(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from live2note.cli import app

    _patch_base_dir(monkeypatch, tmp_path)
    runner = CliRunner()
    runner.invoke(app, ["run", "https://example.com/live.m3u8", "--no-check", "--no-record"])
    task_id = next((tmp_path / "tasks").iterdir()).name
    task_dir = tmp_path / "tasks" / task_id

    notes_dir = task_dir / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    (notes_dir / "final_note.md").write_text("# Test", encoding="utf-8")

    state_file = task_dir / "task_state.json"
    data = json.loads(state_file.read_text(encoding="utf-8"))
    data["final_note_path"] = str(notes_dir / "final_note.md")
    data["getnote_imported"] = True
    state_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    mock_result = GetnoteResult(success=True, message="OK")
    with patch("live2note.storage.getnote.import_to_getnote", return_value=mock_result) as mock_fn:
        result = runner.invoke(app, ["import-getnote", task_id, "--force"])

    assert result.exit_code == 0
    mock_fn.assert_called_once()


def test_import_getnote_not_found(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from live2note.cli import app

    _patch_base_dir(monkeypatch, tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["import-getnote", "nonexistent"])
    assert result.exit_code == 1
