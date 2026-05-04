"""Tests for getnote integration."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from live2note.models.task import TaskState
from live2note.storage.getnote import GetnoteResult, import_to_getnote


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


def test_old_template_ignored(tmp_path: Path):
    """Old {file_path} templates are ignored — API is always used."""
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

        result = import_to_getnote(
            md,
            command_template='getnote save "{file_path}" --title "{title}"',
            title="Test",
        )

    assert result.success
    payload = mock_client.post.call_args[1]["json"]
    assert payload["content"] == content


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
