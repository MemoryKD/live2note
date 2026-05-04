"""getnote integration — import notes via the Open API."""

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


def import_to_getnote(
    file_path: Path | str,
    command_template: str = "getnote save",
    title: str = "",
    tags: list[str] | None = None,
    timeout: int = 120,
) -> GetnoteResult:
    """Read *file_path* and import its Markdown content to getnote via HTTP API.

    Args:
        file_path: Path to the Markdown file to import.
        command_template: Unused (kept for backward compat).
        title: Note title.
        tags: Optional tags.
        timeout: Total timeout in seconds for API calls + polling.

    Returns:
        GetnoteResult with success status and output.
    """
    _ = command_template  # backward compat

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
        "title": title or file_path.stem,
    }
    if tags:
        payload["tags"] = tags

    log.info("Calling getnote API: save note (%d chars)", len(content))

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
        # Check for tasks array (link-style response).
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
