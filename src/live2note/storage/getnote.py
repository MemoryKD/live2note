"""getnote integration — import final_note.md via the Open API.

Only imports ``data/tasks/{task_id}/notes/final_note.md``.
Never imports directories, other tasks, transcripts, chunks, or summaries.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from live2note.logger import get_logger

log = get_logger("storage.getnote")

_API_BASE = os.environ.get("GETNOTE_API_URL", "https://openapi.biji.com")
_SAVE_URL = f"{_API_BASE}/open/api/v1/resource/note/save"
_TASK_URL = f"{_API_BASE}/open/api/v1/resource/note/task/progress"
_POLL_INTERVAL = 2  # seconds
_POLL_MAX = 40       # max ~80 seconds


def _load_auth() -> tuple[str, str]:
    """Return (api_key, client_id) from getnote config or env."""
    api_key = os.environ.get("GETNOTE_API_KEY", "")
    client_id = os.environ.get("GETNOTE_CLIENT_ID", "getnote-cli")

    if not api_key:
        config_path = Path.home() / ".getnote" / "config.json"
        if config_path.is_file():
            try:
                cfg = json.loads(config_path.read_text(encoding="utf-8"))
                api_key = cfg.get("api_key", "")
                client_id = cfg.get("client_id", client_id)
            except (json.JSONDecodeError, OSError):
                pass

    return api_key, client_id


@dataclass(frozen=True)
class GetnoteResult:
    success: bool
    message: str
    stdout: str = ""
    stderr: str = ""


# ── path validation ─────────────────────────────────────────


def validate_final_note_path(task_dir: Path, final_note_path: Path | str) -> Path:
    """Validate that *final_note_path* is safe and correct.

    Rules:
      - Must resolve within *task_dir* (no path traversal).
      - Filename must be ``final_note.md``.
      - Parent directory must be ``notes/``.
      - Must be a regular file (not a directory or symlink).
      - Content must be non-empty.

    Returns the resolved Path on success.
    """
    final_note_path = Path(final_note_path)
    resolved_task = task_dir.resolve()
    resolved_note = final_note_path.resolve()

    # 1. Must be inside task directory.
    task_prefix = str(resolved_task) + os.sep
    if not str(resolved_note).startswith(task_prefix):
        raise ValueError(
            "Invalid final note path: file is outside the task directory.\n"
            f"  Task directory: {resolved_task}\n"
            f"  Note path:      {resolved_note}"
        )

    # 2. Must be a file, not a directory.
    if resolved_note.is_dir():
        raise ValueError(
            "Invalid final note path: points to a directory, not a file.\n"
            f"  Path: {resolved_note}"
        )

    # 3. Must be named "final_note.md".
    if resolved_note.name != "final_note.md":
        raise ValueError(
            f"Invalid final note path: only 'final_note.md' can be imported.\n"
            f"  Got: {resolved_note.name}"
        )

    # 4. Must be in a "notes/" directory.
    if resolved_note.parent.name != "notes":
        raise ValueError(
            "Invalid final note path: must be in a 'notes/' directory.\n"
            f"  Got: {resolved_note.parent}"
        )

    # 5. Must exist.
    if not resolved_note.is_file():
        raise ValueError(
            f"final_note.md not found. Generate it first with 'live2note save'.\n"
            f"  Expected: {resolved_note}"
        )

    # 6. Must not be empty.
    if resolved_note.stat().st_size == 0:
        raise ValueError(
            f"final_note.md is empty. Cannot import an empty note.\n"
            f"  Path: {resolved_note}"
        )

    return resolved_note


# ── title extraction ────────────────────────────────────────


def extract_markdown_title(content: str) -> str:
    """Extract the first level-1 heading from Markdown content.

    Returns the heading text without the ``# `` prefix, or empty string.
    """
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            return stripped[2:].strip()
    return ""


# ── import ──────────────────────────────────────────────────


def import_to_getnote(
    file_path: Path | str,
    title: str = "",
    tags: list[str] | None = None,
    timeout: int = 120,
    dry_run: bool = False,
) -> GetnoteResult:
    """Import a single Markdown file to getnote via the HTTP API.

    Args:
        file_path: Path to the Markdown file (must be final_note.md).
        title: Note title.
        tags: Optional tags.
        timeout: Total timeout in seconds for API calls + polling.
        dry_run: If True, only validate and preview — no API call.

    Returns:
        GetnoteResult with success status and output.
    """
    file_path = Path(file_path)

    if not file_path.is_file():
        return GetnoteResult(
            success=False,
            message=f"File not found: {file_path}",
        )

    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        return GetnoteResult(
            success=False,
            message=f"Failed to read file: {exc}",
        )

    if not content.strip():
        return GetnoteResult(
            success=False,
            message=f"File is empty: {file_path}",
        )

    title = title or file_path.stem
    char_count = len(content)

    # Dry-run: preview only.
    if dry_run:
        log.info("getnote dry-run: would import %s (%d chars)", file_path.name, char_count)
        return GetnoteResult(
            success=True,
            message=f"[dry-run] Would import: {file_path.name} ({char_count} chars)",
        )

    api_key, client_id = _load_auth()
    if not api_key:
        return GetnoteResult(
            success=False,
            message=(
                "getnote API key not found. "
                "Run: getnote auth login --api-key <key> --client-id <id>"
            ),
        )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "X-Client-ID": client_id,
        "Content-Type": "application/json",
    }

    payload = {
        "note_type": "plain_text",
        "content": content,
        "title": title,
    }
    if tags:
        payload["tags"] = tags

    log.info("Calling getnote API: save note (%d chars, title=%s)", char_count, title)

    deadline = time.monotonic() + timeout

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(_SAVE_URL, json=payload, headers=headers)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.error("getnote API request failed: %s", exc)
        return GetnoteResult(
            success=False,
            message=f"API request failed: {exc}",
        )

    body = resp.json()
    if not body.get("success"):
        err = body.get("error", {})
        msg = err.get("message", "Unknown API error") if isinstance(err, dict) else str(err)
        log.warning("getnote API returned error: %s", msg)
        return GetnoteResult(
            success=False,
            message=msg,
            stderr=json.dumps(body, ensure_ascii=False),
        )

    data = body.get("data", {})
    task_id = data.get("task_id") or ""
    if not task_id:
        tasks = data.get("tasks", [])
        if tasks:
            task_id = tasks[0].get("task_id", "")

    # Poll for async task completion.
    if task_id:
        log.info("Polling getnote task: %s", task_id)
        try:
            with httpx.Client(timeout=30) as client:
                for _ in range(_POLL_MAX):
                    if time.monotonic() > deadline:
                        return GetnoteResult(
                            success=False,
                            message=f"Task {task_id} timed out",
                            stdout=json.dumps(body, ensure_ascii=False),
                        )
                    time.sleep(_POLL_INTERVAL)
                    tr = client.post(
                        _TASK_URL,
                        json={"task_id": task_id},
                        headers=headers,
                    )
                    tr.raise_for_status()
                    tb = tr.json()
                    td = tb.get("data", {}) if tb.get("success") else {}
                    status = td.get("status", "")
                    if status in ("done", "success", "completed"):
                        note_id = td.get("note_id", "")
                        log.info("getnote task completed: note_id=%s", note_id)
                        break
                    elif status in ("failed",):
                        return GetnoteResult(
                            success=False,
                            message=f"getnote task failed: {td.get('msg', status)}",
                            stderr=json.dumps(tb, ensure_ascii=False),
                        )
        except httpx.HTTPError as exc:
            log.error("getnote task polling failed: %s", exc)
            return GetnoteResult(
                success=False,
                message=f"Task polling failed: {exc}",
            )

    output = json.dumps(body, ensure_ascii=False)
    log.info("getnote import succeeded")
    return GetnoteResult(
        success=True,
        message="Imported successfully",
        stdout=output,
    )
