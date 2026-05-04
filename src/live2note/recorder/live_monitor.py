"""Live stream monitor — periodically checks if stream is still live.

Runs as a background thread during recording. When the stream goes offline
consistently, triggers a stop via StopController.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Protocol

from live2note.logger import get_logger
from live2note.models.task import StopReason, TaskState

log = get_logger("live_monitor")


class _StopFunc(Protocol):
    def __call__(self, state: TaskState, task_dir: Path, reason: str) -> TaskState: ...


class _SaveFunc(Protocol):
    def __call__(self, state: TaskState) -> None: ...


class _CheckLiveFunc(Protocol):
    def __call__(self, url: str) -> object:  # returns CheckResult
        ...


class LiveMonitor:
    """Background monitor that checks stream liveness.

    Usage:
        monitor = LiveMonitor(...)
        monitor.start()
        ...  # recording happens here
        monitor.stop()
    """

    def __init__(
        self,
        state: TaskState,
        task_dir: Path,
        check_live_fn: _CheckLiveFunc,
        stop_fn: _StopFunc,
        save_fn: _SaveFunc,
        interval_seconds: int = 60,
        max_failures: int = 3,
    ) -> None:
        self._state = state
        self._task_dir = task_dir
        self._check_live_fn = check_live_fn
        self._stop_fn = stop_fn
        self._save_fn = save_fn
        self._interval = max(interval_seconds, 10)
        self._max_failures = max_failures
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._consecutive_failures = 0

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log.info("LiveMonitor started (interval=%ds, max_failures=%d)",
                 self._interval, self._max_failures)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        log.info("LiveMonitor stopped.")

    def _run(self) -> None:
        # Wait one interval before first check.
        if self._stop_event.wait(timeout=self._interval):
            return

        while not self._stop_event.is_set():
            try:
                self._check_once()
            except Exception:
                log.exception("LiveMonitor check failed unexpectedly")
                self._consecutive_failures += 1

            if self._consecutive_failures >= self._max_failures:
                log.warning(
                    "Live check failed %d times in a row — stopping.",
                    self._consecutive_failures,
                )
                self._stop_fn(
                    self._state, self._task_dir,
                    StopReason.NO_DATA_TIMEOUT.value,
                )
                break

            if self._stop_event.wait(timeout=self._interval):
                break

    def _check_once(self) -> None:
        result = self._check_live_fn(self._state.url)
        is_live = getattr(result, "is_live", True)
        self._state.record_stream_check(is_live)
        self._save_fn(self._state)

        if not is_live:
            self._consecutive_failures += 1
            log.info(
                "Stream not live (failure %d/%d)",
                self._consecutive_failures, self._max_failures,
            )
        else:
            self._consecutive_failures = 0
            log.debug("Stream is live.")
