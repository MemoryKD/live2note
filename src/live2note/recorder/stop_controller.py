"""Unified stop controller — manages stop signals, ffmpeg termination, and state transitions."""

from __future__ import annotations

import json
import os
import signal
import subprocess
from pathlib import Path

from live2note.logger import get_logger
from live2note.models.task import StopReason, TaskState

log = get_logger("stop")

STOP_FLAG_NAME = "stop.flag"
CONTROL_DIR_NAME = "control"


def _control_dir(task_dir: Path) -> Path:
    return task_dir / CONTROL_DIR_NAME


def _stop_flag_path(task_dir: Path) -> Path:
    return _control_dir(task_dir) / STOP_FLAG_NAME


# ── Public API ──────────────────────────────────────────────


def write_stop_flag(task_dir: Path, reason: str = StopReason.MANUAL_STOP.value) -> Path:
    """Create control/stop.flag file. Returns the path."""
    ctrl = _control_dir(task_dir)
    ctrl.mkdir(parents=True, exist_ok=True)
    flag = ctrl / STOP_FLAG_NAME
    payload = {"reason": reason, "time": _now_iso()}
    # Atomic write: write to tmp then rename.
    tmp = flag.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(flag)
    log.info("Stop flag written: %s", flag)
    return flag


def read_stop_flag(task_dir: Path) -> dict | None:
    """Read stop.flag if it exists, else None."""
    flag = _stop_flag_path(task_dir)
    if not flag.is_file():
        return None
    try:
        return json.loads(flag.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"reason": "unknown"}


def remove_stop_flag(task_dir: Path) -> None:
    flag = _stop_flag_path(task_dir)
    if flag.is_file():
        flag.unlink(missing_ok=True)


def is_stop_flag_present(task_dir: Path) -> bool:
    return _stop_flag_path(task_dir).is_file()


def request_stop(
    state: TaskState,
    task_dir: Path,
    reason: str = StopReason.MANUAL_STOP.value,
) -> TaskState:
    """Request a stop on a task. Updates state and writes stop.flag."""
    state.request_stop(reason)
    write_stop_flag(task_dir, reason)
    log.info("Stop requested for task %s, reason=%s", state.task_id, reason)
    return state


def stop_ffmpeg(
    state: TaskState,
    grace_seconds: int = 10,
) -> bool:
    """Attempt graceful stop of ffmpeg, then force kill. Returns True if stopped."""
    pid = state.ffmpeg_pid
    if pid is None:
        log.debug("No ffmpeg_pid recorded, nothing to stop.")
        return True

    log.info("Stopping ffmpeg pid=%d (grace=%ds)", pid, grace_seconds)

    if not _is_process_alive(pid):
        log.info("ffmpeg pid=%d already exited.", pid)
        return True

    # Graceful: SIGINT (ffmpeg closes output on SIGINT).
    _send_terminate(pid)
    if not _wait_for_exit(pid, grace_seconds):
        log.warning("ffmpeg pid=%d did not exit in %ds, force killing.", pid, grace_seconds)
        _force_kill(pid)
        _wait_for_exit(pid, 5)

    alive = _is_process_alive(pid)
    if alive:
        log.error("ffmpeg pid=%d still alive after kill.", pid)
    else:
        log.info("ffmpeg pid=%d stopped.", pid)
    return not alive


# ── Process helpers ─────────────────────────────────────────


def _is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _send_terminate(pid: int) -> None:
    try:
        if hasattr(signal, "CTRL_C_EVENT"):
            os.kill(pid, signal.CTRL_C_EVENT)
        else:
            os.kill(pid, signal.SIGINT)
    except (OSError, ProcessLookupError):
        pass


def _force_kill(pid: int) -> None:
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F", "/T"],
                capture_output=True, timeout=10,
            )
        else:
            os.kill(pid, signal.SIGKILL)
    except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
        pass


def _wait_for_exit(pid: int, timeout: float) -> bool:
    """Wait for process to exit. Returns True if it exited."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _is_process_alive(pid):
            return True
        time.sleep(0.5)
    return not _is_process_alive(pid)


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
