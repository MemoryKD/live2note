"""Tests for getnote integration."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from live2note.models.task import TaskState
from live2note.storage.getnote import (
    GetnoteResult,
    extract_markdown_title,
    import_to_getnote,
    validate_final_note_path,
)


def _mock_httpx_response(success: bool = True, data: dict | None = None,
                         error: dict | None = None, status_code: int = 200):
    """Build a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    body = {"success": success, "data": data or {}, "error": error}
    resp.json.return_value = body
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        import httpx
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


# ── import_to_getnote ───────────────────────────────────────


def test_file_not_found():
    result = import_to_getnote("/nonexistent/file.md")
    assert not result.success
    assert "not found" in result.message.lower()


def test_empty_file_rejected(tmp_path: Path):
    md = tmp_path / "empty.md"
    md.write_text("   \n  ", encoding="utf-8")
    result = import_to_getnote(md)
    assert not result.success
    assert "empty" in result.message.lower()


def test_read_error_handled(tmp_path: Path):
    md = tmp_path / "note.md"
    md.write_text("# Test", encoding="utf-8")
    result = import_to_getnote(tmp_path)  # directory, not file
    assert not result.success
    assert "not found" in result.message.lower()


def test_no_api_key(tmp_path: Path):
    md = tmp_path / "note.md"
    md.write_text("# Test", encoding="utf-8")
    with patch("live2note.storage.getnote._load_auth", return_value=("", "")):
        result = import_to_getnote(md)
    assert not result.success
    assert "API key" in result.message


def test_success(tmp_path: Path):
    md = tmp_path / "note.md"
    content = "# Test Note\n\nMulti-line content here."
    md.write_text(content, encoding="utf-8")

    with (
        patch("live2note.storage.getnote._load_auth",
              return_value=("sk-test", "test-client")),
        patch("live2note.storage.getnote.httpx.Client") as mock_client_cls,
    ):
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.return_value = _mock_httpx_response(
            success=True, data={"note_id": "12345"}
        )
        mock_client_cls.return_value = mock_client

        result = import_to_getnote(md, title="Test Title", tags=["tag1"])

    assert result.success
    assert "success" in result.message.lower()

    # Verify the API was called with correct payload.
    call_args = mock_client.post.call_args
    assert call_args is not None
    url = call_args[0][0]
    assert "/open/api/v1/resource/note/save" in url
    payload = call_args[1]["json"]
    assert payload["note_type"] == "plain_text"
    assert payload["content"] == content
    assert payload["title"] == "Test Title"
    assert payload["tags"] == ["tag1"]


def test_api_error(tmp_path: Path):
    md = tmp_path / "note.md"
    md.write_text("# Test", encoding="utf-8")

    with (
        patch("live2note.storage.getnote._load_auth",
              return_value=("sk-test", "test-client")),
        patch("live2note.storage.getnote.httpx.Client") as mock_client_cls,
    ):
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.return_value = _mock_httpx_response(
            success=False, error={"message": "Rate limited"}, status_code=200
        )
        mock_client_cls.return_value = mock_client

        result = import_to_getnote(md)

    assert not result.success
    assert "Rate limited" in result.message


def test_http_error(tmp_path: Path):
    md = tmp_path / "note.md"
    md.write_text("# Test", encoding="utf-8")

    with (
        patch("live2note.storage.getnote._load_auth",
              return_value=("sk-test", "test-client")),
        patch("live2note.storage.getnote.httpx.Client") as mock_client_cls,
    ):
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.return_value = _mock_httpx_response(
            success=False, status_code=500
        )
        mock_client_cls.return_value = mock_client

        result = import_to_getnote(md)

    assert not result.success
    assert "api request" in result.message.lower()


def test_task_polling(tmp_path: Path):
    md = tmp_path / "note.md"
    md.write_text("# Test", encoding="utf-8")

    with (
        patch("live2note.storage.getnote._load_auth",
              return_value=("sk-test", "test-client")),
        patch("live2note.storage.getnote.httpx.Client") as mock_client_cls,
        patch("live2note.storage.getnote._POLL_INTERVAL", 0),  # speed up
    ):
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client

        # First call: save returns task_id.
        save_resp = _mock_httpx_response(
            success=True, data={"task_id": "task-123"}
        )
        # Second call: poll returns done.
        poll_resp = _mock_httpx_response(
            success=True, data={"task_id": "task-123", "status": "done", "note_id": "note-456"}
        )
        mock_client.post.side_effect = [save_resp, poll_resp]
        mock_client_cls.return_value = mock_client

        result = import_to_getnote(md)

    assert result.success
    assert mock_client.post.call_count == 2


def test_default_title_from_filename(tmp_path: Path):
    md = tmp_path / "my_note.md"
    md.write_text("# Test", encoding="utf-8")

    with (
        patch("live2note.storage.getnote._load_auth",
              return_value=("sk-test", "test-client")),
        patch("live2note.storage.getnote.httpx.Client") as mock_client_cls,
    ):
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.return_value = _mock_httpx_response(
            success=True, data={}
        )
        mock_client_cls.return_value = mock_client

        result = import_to_getnote(md)

    assert result.success
    payload = mock_client.post.call_args[1]["json"]
    assert payload["title"] == "my_note"


def test_import_single_file_only(tmp_path: Path):
    """import_to_getnote always imports exactly one file via HTTP API."""
    md = tmp_path / "note.md"
    content = "# Real content"
    md.write_text(content, encoding="utf-8")

    with (
        patch("live2note.storage.getnote._load_auth",
              return_value=("sk-test", "test-client")),
        patch("live2note.storage.getnote.httpx.Client") as mock_client_cls,
    ):
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.return_value = _mock_httpx_response(
            success=True, data={}
        )
        mock_client_cls.return_value = mock_client

        result = import_to_getnote(md, title="Test")

    assert result.success
    payload = mock_client.post.call_args[1]["json"]
    assert payload["content"] == content
    # Only one file was sent — no directory scanning
    assert len(payload["content"]) > 0


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
    assert "not found" in result.output.lower() or "generate" in result.output.lower()


def test_import_getnote_success(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from live2note.cli import app

    _patch_base_dir(monkeypatch, tmp_path)
    runner = CliRunner()
    runner.invoke(app, ["run", "https://example.com/live.m3u8", "--no-check", "--no-record"])
    task_id = next((tmp_path / "tasks").iterdir()).name
    task_dir = tmp_path / "tasks" / task_id

    notes_dir = task_dir / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    (notes_dir / "final_note.md").write_text("# Test Note", encoding="utf-8")

    state_file = task_dir / "task_state.json"
    data = json.loads(state_file.read_text(encoding="utf-8"))
    data["final_note_path"] = str(notes_dir / "final_note.md")
    state_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    mock_result = GetnoteResult(success=True, message="OK", stdout="saved")
    with patch("live2note.storage.getnote.import_to_getnote", return_value=mock_result):
        result = runner.invoke(app, ["import-getnote", task_id])

    assert result.exit_code == 0
    assert "succeeded" in result.output.lower()

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

    assert result.exit_code == 0
    assert "failed" in result.output.lower()

    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert data["getnote_imported"] is False
    assert data["getnote_error"] == "auth failed"
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


# ── validate_final_note_path tests ───────────────────────────


class TestValidateFinalNotePath:
    def test_valid_path(self, tmp_path: Path):
        task_dir = tmp_path / "task_A"
        notes_dir = task_dir / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        fn = notes_dir / "final_note.md"
        fn.write_text("# Test", encoding="utf-8")
        result = validate_final_note_path(task_dir, fn)
        assert result == fn.resolve()

    def test_default_path_in_task_dir(self, tmp_path: Path):
        task_dir = tmp_path / "task_X"
        notes_dir = task_dir / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        default_path = notes_dir / "final_note.md"
        default_path.write_text("# Content", encoding="utf-8")
        result = validate_final_note_path(task_dir, default_path)
        assert result.name == "final_note.md"

    def test_rejects_wrong_filename(self, tmp_path: Path):
        task_dir = tmp_path / "task_B"
        notes_dir = task_dir / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        wrong_file = notes_dir / "other.md"
        wrong_file.write_text("# Not a final note", encoding="utf-8")
        with pytest.raises(ValueError, match="only 'final_note.md'"):
            validate_final_note_path(task_dir, wrong_file)

    def test_rejects_wrong_directory(self, tmp_path: Path):
        task_dir = tmp_path / "task_C"
        task_dir.mkdir(parents=True)
        wrong_dir = task_dir / "final_note.md"
        wrong_dir.write_text("# Wrong location", encoding="utf-8")
        with pytest.raises(ValueError, match="must be in a 'notes/' directory"):
            validate_final_note_path(task_dir, wrong_dir)

    def test_rejects_path_traversal(self, tmp_path: Path):
        task_dir = tmp_path / "task_D"
        notes_dir = task_dir / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        # Create a valid final_note.md so the file exists check passes.
        fn_valid = notes_dir / "final_note.md"
        fn_valid.write_text("# Ok", encoding="utf-8")

        # Now test with a path that tries to escape.
        escape_path = (notes_dir / "../../task_E/notes/final_note.md").resolve()
        escape_path.parent.mkdir(parents=True, exist_ok=True)
        escape_path.write_text("# Escaped", encoding="utf-8")
        with pytest.raises(ValueError, match="outside the task directory"):
            validate_final_note_path(task_dir, escape_path)

    def test_rejects_directory(self, tmp_path: Path):
        task_dir = tmp_path / "task_F"
        notes_dir = task_dir / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        with pytest.raises(ValueError, match="directory"):
            validate_final_note_path(task_dir, notes_dir)

    def test_rejects_missing_file(self, tmp_path: Path):
        task_dir = tmp_path / "task_G"
        notes_dir = task_dir / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        missing = notes_dir / "final_note.md"
        with pytest.raises(ValueError, match="not found"):
            validate_final_note_path(task_dir, missing)

    def test_rejects_empty_file(self, tmp_path: Path):
        task_dir = tmp_path / "task_H"
        notes_dir = task_dir / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        fn = notes_dir / "final_note.md"
        fn.write_text("", encoding="utf-8")
        with pytest.raises(ValueError, match="empty"):
            validate_final_note_path(task_dir, fn)


# ── getnote import isolation tests ────────────────────────────


class TestGetnoteIsolation:
    """Ensure only the current task's final_note.md is imported."""

    def test_other_tasks_not_imported(self, tmp_path: Path, monkeypatch):
        """Task A import should not touch Task B's files."""
        from typer.testing import CliRunner

        from live2note.cli import app

        _patch_base_dir(monkeypatch, tmp_path)
        runner = CliRunner()

        # Create task_A with final_note.md
        runner.invoke(app, ["run", "https://example.com/a.m3u8", "--no-check", "--no-record"])
        task_a = next((tmp_path / "tasks").iterdir()).name
        task_a_dir = tmp_path / "tasks" / task_a
        notes_a = task_a_dir / "notes"
        notes_a.mkdir(parents=True, exist_ok=True)
        (notes_a / "final_note.md").write_text("# Task A Note", encoding="utf-8")
        state_a = task_a_dir / "task_state.json"
        data_a = json.loads(state_a.read_text(encoding="utf-8"))
        data_a["final_note_path"] = str(notes_a / "final_note.md")
        state_a.write_text(json.dumps(data_a, ensure_ascii=False), encoding="utf-8")

        # Add transcript and prompt files that should NEVER be imported
        transcripts = task_a_dir / "transcripts"
        transcripts.mkdir(parents=True, exist_ok=True)
        (transcripts / "segment_001.md").write_text("# transcript", encoding="utf-8")
        prompts = task_a_dir / "prompts"
        prompts.mkdir(parents=True, exist_ok=True)
        (prompts / "chunk_001_prompt.md").write_text("# prompt", encoding="utf-8")
        chunks_dir = task_a_dir / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)
        (chunks_dir / "chunks.md").write_text("# chunk", encoding="utf-8")

        # Create task_B with its own final_note.md (should NOT be imported)
        runner.invoke(app, ["run", "https://example.com/b.m3u8", "--no-check", "--no-record"])
        all_tasks = sorted((tmp_path / "tasks").iterdir())
        task_b = [t for t in all_tasks if t.name != task_a][0].name
        task_b_dir = tmp_path / "tasks" / task_b
        notes_b = task_b_dir / "notes"
        notes_b.mkdir(parents=True, exist_ok=True)
        (notes_b / "final_note.md").write_text("# Task B Note", encoding="utf-8")

        mock_result = GetnoteResult(success=True, message="OK", stdout="saved")
        with patch("live2note.storage.getnote.import_to_getnote", return_value=mock_result) as mock_fn:
            result = runner.invoke(app, ["import-getnote", task_a])

        assert result.exit_code == 0
        assert "succeeded" in result.output.lower()
        # Should be called exactly once with task_A's file
        mock_fn.assert_called_once()
        call_path = Path(mock_fn.call_args[1]["file_path"])
        assert call_path.name == "final_note.md"
        assert call_path.parent.name == "notes"
        assert task_a in str(call_path)
        assert task_b not in str(call_path)

    def test_transcripts_not_imported(self, tmp_path: Path, monkeypatch):
        """Transcripts should never be imported to getnote."""
        from typer.testing import CliRunner

        from live2note.cli import app

        _patch_base_dir(monkeypatch, tmp_path)
        runner = CliRunner()
        runner.invoke(app, ["run", "https://example.com/test.m3u8", "--no-check", "--no-record"])
        task_id = next((tmp_path / "tasks").iterdir()).name
        task_dir = tmp_path / "tasks" / task_id

        notes_dir = task_dir / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        (notes_dir / "final_note.md").write_text("# Real Note", encoding="utf-8")

        state_file = task_dir / "task_state.json"
        data = json.loads(state_file.read_text(encoding="utf-8"))
        data["final_note_path"] = str(notes_dir / "final_note.md")
        state_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        mock_result = GetnoteResult(success=True, message="OK")
        with patch("live2note.storage.getnote.import_to_getnote", return_value=mock_result) as mock_fn:
            result = runner.invoke(app, ["import-getnote", task_id])

        assert result.exit_code == 0
        mock_fn.assert_called_once()
        imported_path = Path(mock_fn.call_args[1]["file_path"])
        # Only checks the path components we care about, not tmp_path prefixes
        assert imported_path.name == "final_note.md"
        assert imported_path.parent.name == "notes"
        assert "transcripts" not in str(imported_path.relative_to(task_dir.parent))
        assert "prompts" not in str(imported_path.relative_to(task_dir.parent))


# ── dry-run tests ─────────────────────────────────────────────


class TestDryRun:
    def test_dry_run_displays_info(self, tmp_path: Path, monkeypatch):
        from typer.testing import CliRunner

        from live2note.cli import app

        _patch_base_dir(monkeypatch, tmp_path)
        runner = CliRunner()
        runner.invoke(app, ["run", "https://example.com/test.m3u8", "--no-check", "--no-record"])
        task_id = next((tmp_path / "tasks").iterdir()).name
        task_dir = tmp_path / "tasks" / task_id

        notes_dir = task_dir / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        (notes_dir / "final_note.md").write_text("# Test Note Content", encoding="utf-8")

        state_file = task_dir / "task_state.json"
        data = json.loads(state_file.read_text(encoding="utf-8"))
        data["final_note_path"] = str(notes_dir / "final_note.md")
        state_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        result = runner.invoke(app, ["import-getnote", task_id, "--dry-run"])

        assert result.exit_code == 0
        assert task_id in result.output
        assert "final_note.md" in result.output

    def test_dry_run_does_not_call_api(self, tmp_path: Path, monkeypatch):
        from typer.testing import CliRunner

        from live2note.cli import app

        _patch_base_dir(monkeypatch, tmp_path)
        runner = CliRunner()
        runner.invoke(app, ["run", "https://example.com/test.m3u8", "--no-check", "--no-record"])
        task_id = next((tmp_path / "tasks").iterdir()).name
        task_dir = tmp_path / "tasks" / task_id

        notes_dir = task_dir / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        (notes_dir / "final_note.md").write_text("# Test", encoding="utf-8")

        state_file = task_dir / "task_state.json"
        data = json.loads(state_file.read_text(encoding="utf-8"))
        data["final_note_path"] = str(notes_dir / "final_note.md")
        state_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        mock_result = GetnoteResult(success=True, message="OK")
        with patch("live2note.storage.getnote.import_to_getnote", return_value=mock_result) as mock_fn:
            result = runner.invoke(app, ["import-getnote", task_id, "--dry-run"])

        assert result.exit_code == 0
        # import_to_getnote must NOT be called for dry-run
        mock_fn.assert_not_called()

    def test_dry_run_file_not_found(self, tmp_path: Path, monkeypatch):
        from typer.testing import CliRunner

        from live2note.cli import app

        _patch_base_dir(monkeypatch, tmp_path)
        runner = CliRunner()
        runner.invoke(app, ["run", "https://example.com/test.m3u8", "--no-check", "--no-record"])
        task_id = next((tmp_path / "tasks").iterdir()).name

        # No notes/ directory — should show error
        result = runner.invoke(app, ["import-getnote", task_id, "--dry-run"])
        assert result.exit_code == 0
        # Should indicate the file was not found
        assert "not found" in result.output.lower() or "generate" in result.output.lower()

    def test_dry_run_empty_file(self, tmp_path: Path, monkeypatch):
        from typer.testing import CliRunner

        from live2note.cli import app

        _patch_base_dir(monkeypatch, tmp_path)
        runner = CliRunner()
        runner.invoke(app, ["run", "https://example.com/test.m3u8", "--no-check", "--no-record"])
        task_id = next((tmp_path / "tasks").iterdir()).name
        task_dir = tmp_path / "tasks" / task_id

        notes_dir = task_dir / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        (notes_dir / "final_note.md").write_text("", encoding="utf-8")

        state_file = task_dir / "task_state.json"
        data = json.loads(state_file.read_text(encoding="utf-8"))
        data["final_note_path"] = str(notes_dir / "final_note.md")
        state_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        result = runner.invoke(app, ["import-getnote", task_id, "--dry-run"])
        assert result.exit_code == 0
        assert "empty" in result.output.lower()


# ── dry_run mode in import_to_getnote ─────────────────────────


def test_import_to_getnote_dry_run(tmp_path: Path):
    md = tmp_path / "final_note.md"
    md.write_text("# Dry run test content", encoding="utf-8")
    result = import_to_getnote(md, title="Test", dry_run=True)
    assert result.success
    assert "dry-run" in result.message.lower()
    assert "would import" in result.message.lower()


# ── extract_markdown_title tests ──────────────────────────────


class TestExtractMarkdownTitle:
    def test_extracts_h1(self):
        content = "# 抖音直播知识笔记：主播A - 精彩直播\n\n## 基本信息\n..."
        assert extract_markdown_title(content) == "抖音直播知识笔记：主播A - 精彩直播"

    def test_extracts_first_h1_only(self):
        content = "# First Title\n\nSome text\n\n# Second Title\n"
        assert extract_markdown_title(content) == "First Title"

    def test_ignores_h2(self):
        content = "## 基本信息\n- 平台：抖音\n"
        assert extract_markdown_title(content) == ""

    def test_trims_whitespace(self):
        content = "   #    抖音直播笔记   \n\n## 基本信息\n"
        assert extract_markdown_title(content) == "抖音直播笔记"

    def test_empty_content(self):
        assert extract_markdown_title("") == ""

    def test_no_heading_returns_empty(self):
        content = "This is just some text without headings."
        assert extract_markdown_title(content) == ""


# ── Douyin metadata default tests ─────────────────────────────


class TestDouyinMetadataDefaults:
    def test_display_title_from_resolver(self):
        """DouyinResolver.check_live returns safe defaults even with no real data."""
        from live2note.resolvers.douyin_resolver import DouyinResolver

        dr = DouyinResolver({"yt_dlp_enabled": False, "streamlink_enabled": False, "timeout": 5})
        result = dr.check_live("https://live.douyin.com/12345")
        assert result.platform == "douyin"
        assert result.title == "抖音直播"
        assert result.streamer == "未知主播"
        # display_title is not on CheckResult but the calling code computes it

    def test_build_final_note_douyin_defaults(self):
        """final_note uses display_title with safe defaults for Douyin."""
        from live2note.processor.final_note_builder import build_final_note

        metadata = {"platform": "douyin"}
        note = build_final_note("task_X", metadata, [], None)
        assert "抖音" in note.title
        assert "未知主播" in note.title
        assert "直播" in note.title

    def test_build_final_note_source_url_preserved(self):
        """source_url is the original Douyin URL, not the stream URL."""
        from live2note.processor.final_note_builder import build_final_note

        metadata = {
            "platform": "douyin",
            "source_url": "https://live.douyin.com/99999",
            "stream_url": "http://pull-flv.douyincdn.com/secret_stream.flv?sign=abc",
        }
        note = build_final_note("task_Y", metadata, [], None)
        assert note.source_url == "https://live.douyin.com/99999"
        assert "douyincdn.com" not in note.source_url
        # Stream URL must not appear as title
        assert "flv" not in note.title.lower()
