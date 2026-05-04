"""Path utilities for live2note data directories."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def default_base_dir() -> Path:
    """Return the default task output directory: ~/.live2note/data/tasks"""
    return Path.home() / ".live2note" / "data" / "tasks"


def config_search_paths() -> list[Path]:
    """Return candidate paths for config.yaml, ordered by priority."""
    return [
        Path.cwd() / "live2note.yaml",
        Path.cwd() / "config.yaml",
        Path.home() / ".live2note" / "config.yaml",
    ]


def generate_task_id() -> str:
    """Generate a unique task ID from the current timestamp + random suffix."""
    from secrets import token_hex

    now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    return f"{now}_{token_hex(3)}"


def task_dir(base: Path, task_id: str) -> Path:
    """Return the directory for a specific task."""
    return base / task_id


def ensure_subdirs(task_path: Path) -> dict[str, Path]:
    """Create and return standard task subdirectories."""
    names = [
        "audio_segments",
        "transcripts",
        "chunks",
        "summaries",
        "notes",
        "logs",
    ]
    dirs = {}
    for name in names:
        d = task_path / name
        d.mkdir(parents=True, exist_ok=True)
        dirs[name] = d
    return dirs
