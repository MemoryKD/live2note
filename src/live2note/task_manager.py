"""Task lifecycle: create, load, list, save, resume."""

from __future__ import annotations

import json
from pathlib import Path

from live2note.adapters.registry import get_adapter
from live2note.logger import get_logger
from live2note.models.task import (
    STEP_TO_STATUS,
    TaskMetadata,
    TaskState,
    TaskStatus,
)
from live2note.paths import ensure_subdirs, generate_task_id, task_dir

log = get_logger("task")

STATE_FILE = "task_state.json"
METADATA_FILE = "metadata.json"


def detect_source_type(url: str) -> str:
    """Detect platform from URL using the adapter registry."""
    adapter = get_adapter(url)
    if adapter is not None:
        return adapter.get_platform()
    return "generic"


# ── TaskManager ─────────────────────────────────────────────


class TaskManager:
    """Manages task creation, persistence, and lookup."""

    def __init__(self, base_dir: Path) -> None:
        self._base = base_dir

    @property
    def base_dir(self) -> Path:
        return self._base

    # ── create ───────────────────────────────────────────────

    def create(
        self,
        url: str,
        platform: str = "auto",
        duration: int = 0,
        getnote: bool = False,
        getnote_tags: list[str] | None = None,
        metadata: TaskMetadata | None = None,
    ) -> TaskState:
        task_id = generate_task_id()
        source_type = detect_source_type(url) if platform == "auto" else platform

        state = TaskState(
            task_id=task_id,
            url=url,
            platform=platform,
            source_type=source_type,
            duration=duration,
            getnote_enabled=getnote,
            getnote_tags=getnote_tags or [],
            metadata=metadata or TaskMetadata(url=url, platform=source_type),
        )

        t_dir = task_dir(self._base, task_id)
        ensure_subdirs(t_dir)
        self._save(state, t_dir)
        self._save_metadata(state, t_dir)

        log.info("Task created: %s (%s)", task_id, source_type)
        return state

    # ── load / list ──────────────────────────────────────────

    def load(self, task_id: str) -> TaskState:
        t_dir = task_dir(self._base, task_id)
        state_file = t_dir / STATE_FILE
        if not state_file.is_file():
            raise FileNotFoundError(f"Task not found: {task_id}")
        data = json.loads(state_file.read_text(encoding="utf-8"))
        return TaskState.from_dict(data)

    def get_latest(self) -> TaskState | None:
        dirs = self._sorted_task_dirs()
        if not dirs:
            return None
        for d in dirs:
            if (d / STATE_FILE).is_file():
                return self._load_from_dir(d)
        return None

    def list_tasks(
        self,
        status_filter: str | None = None,
        limit: int = 20,
    ) -> list[TaskState]:
        results: list[TaskState] = []
        for d in self._sorted_task_dirs():
            state_file = d / STATE_FILE
            if not state_file.is_file():
                continue
            data = json.loads(state_file.read_text(encoding="utf-8"))
            if status_filter and data.get("status") != status_filter:
                continue
            results.append(TaskState.from_dict(data))
            if len(results) >= limit:
                break
        return results

    def task_exists(self, task_id: str) -> bool:
        return (task_dir(self._base, task_id) / STATE_FILE).is_file()

    # ── save ─────────────────────────────────────────────────

    def save(self, state: TaskState) -> None:
        t_dir = task_dir(self._base, state.task_id)
        self._save(state, t_dir)

    def save_metadata(self, state: TaskState) -> None:
        t_dir = task_dir(self._base, state.task_id)
        self._save_metadata(state, t_dir)

    # ── resume ───────────────────────────────────────────────

    def resume(self, task_id: str) -> TaskState:
        """Load a task and prepare it for resumption.

        - Increments retry_count.
        - If status is COMPLETED or FAILED, resets to the last good step.
        - Returns the updated state ready for pipeline to continue.
        """
        state = self.load(task_id)

        if state.status == TaskStatus.COMPLETED.value:
            log.info("Task %s already completed, nothing to resume.", task_id)
            return state

        # Determine the next step to run.
        next_step = state.next_step()
        if next_step is None:
            log.info("Task %s: all steps done, marking completed.", task_id)
            state.mark_completed()
            self.save(state)
            return state

        state.retry_count += 1
        state.error_message = None
        state.set_step(next_step)

        if state.status in (
            TaskStatus.FAILED.value,
            TaskStatus.STOPPED.value,
        ):
            state.set_status(STEP_TO_STATUS.get(next_step, TaskStatus.CHECKING))

        state.touch()
        self.save(state)

        log.info(
            "Task %s resumed (retry=%d), next step: %s",
            task_id,
            state.retry_count,
            next_step,
        )
        return state

    # ── internal ─────────────────────────────────────────────

    def _save(self, state: TaskState, t_dir: Path) -> None:
        t_dir.mkdir(parents=True, exist_ok=True)
        path = t_dir / STATE_FILE
        path.write_text(
            json.dumps(state.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _save_metadata(self, state: TaskState, t_dir: Path) -> None:
        path = t_dir / METADATA_FILE
        path.write_text(
            json.dumps(state.metadata.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _sorted_task_dirs(self) -> list[Path]:
        if not self._base.is_dir():
            return []
        return sorted(
            [d for d in self._base.iterdir() if d.is_dir()],
            key=lambda d: d.name,
            reverse=True,
        )

    def _load_from_dir(self, d: Path) -> TaskState:
        data = json.loads((d / STATE_FILE).read_text(encoding="utf-8"))
        return TaskState.from_dict(data)

