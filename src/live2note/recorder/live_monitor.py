"""Live stream monitor — periodically checks if stream is still live.

Runs as a background thread during recording. Distinguishes between:
  - LIVE:    stream confirmed live, resets all counters
  - NOT_LIVE: platform confirmed offline, increments live_end_confirm_count
  - ERROR/UNKNOWN: check failed (network/timeout), increments stream_error_count

Triggers stop only on sufficient consecutive confirmations.
"""

from __future__ import annotations

import threading
from contextlib import nullcontext
from pathlib import Path
from typing import Protocol

from live2note.logger import get_logger
from live2note.models.task import LiveCheckStatus, StopReason, TaskState

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

    Thresholds are configurable:
      - live_end_confirmations: consecutive NOT_LIVE results before confirming end
      - max_failures:       consecutive ERROR/UNKNOWN results before stopping

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
        max_failures: int = 5,
        live_end_confirmations: int = 3,
        lock: threading.Lock | None = None,
    ) -> None:
        self._state = state
        self._task_dir = task_dir
        self._check_live_fn = check_live_fn
        self._stop_fn = stop_fn
        self._save_fn = save_fn
        self._lock = lock
        self._interval = max(interval_seconds, 10)
        self._max_failures = max_failures
        self._live_end_confirmations = live_end_confirmations
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._consecutive_failures = 0

    def _guard(self):
        """Context manager that acquires the lock if available."""
        return self._lock if self._lock is not None else nullcontext()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log.info("LiveMonitor started (interval=%ds, max_failures=%d, live_end_confirmations=%d)",
                 self._interval, self._max_failures, self._live_end_confirmations)

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
                with self._guard():
                    self._consecutive_failures += 1
                    self._state.record_live_check(LiveCheckStatus.UNKNOWN.value)
                    self._save_fn(self._state)
                if self._consecutive_failures >= self._max_failures:
                    log.warning(
                        "Live check threw exception %d times in a row — stopping.",
                        self._consecutive_failures,
                    )
                    self._stop_fn(
                        self._state, self._task_dir,
                        StopReason.STREAM_INTERRUPTED.value,
                    )
                    break

            if self._stop_event.wait(timeout=self._interval):
                break

    def _check_once(self) -> None:
        """Run a single live check and update counters."""
        result = self._check_live_fn(self._state.url)
        live_status = getattr(result, "live_status", LiveCheckStatus.UNKNOWN.value)

        with self._guard():
            self._state.record_live_check(live_status)
            self._save_fn(self._state)

            if live_status == LiveCheckStatus.LIVE.value:
                # Stream confirmed live — reset all counters.
                if self._consecutive_failures > 0 or self._state.live_end_confirm_count > 0:
                    log.info("Stream is live again after %d failures / %d not_live confirmations.",
                             self._consecutive_failures, self._state.live_end_confirm_count)
                self._consecutive_failures = 0
                self._state.live_end_confirm_count = 0
                self._save_fn(self._state)
                log.debug("Stream is live.")

            elif live_status == LiveCheckStatus.NOT_LIVE.value:
                # Platform confirmed not live — increment live end confirmation counter.
                # Reset error counter since NOT_LIVE is a definitive answer.
                self._consecutive_failures = 0
                self._state.live_end_confirm_count += 1
                self._save_fn(self._state)
                log.info(
                    "Stream NOT_LIVE (confirmation %d/%d)",
                    self._state.live_end_confirm_count,
                    self._live_end_confirmations,
                )
                if self._state.live_end_confirm_count >= self._live_end_confirmations:
                    log.warning(
                        "Stream confirmed not live after %d checks — stopping.",
                        self._live_end_confirmations,
                    )
                    self._state.mark_live_ended_confirmed()
                    self._save_fn(self._state)
                    self._stop_fn(
                        self._state, self._task_dir,
                        StopReason.LIVE_ENDED_CONFIRMED.value,
                    )
                    self._stop_event.set()

            elif live_status in (LiveCheckStatus.ERROR.value, LiveCheckStatus.UNKNOWN.value):
                # Check failed (network issue, anti-bot, timeout).
                # Don't touch live_end_confirm_count — lack of answer is not "not live".
                self._consecutive_failures += 1
                log.info(
                    "Live check %s (error %d/%d)",
                    live_status,
                    self._consecutive_failures,
                    self._max_failures,
                )
                if self._consecutive_failures >= self._max_failures:
                    log.warning(
                        "Live check failed %d times in a row (%s) — stopping.",
                        self._consecutive_failures, live_status,
                    )
                    self._stop_fn(
                        self._state, self._task_dir,
                        StopReason.STREAM_INTERRUPTED.value,
                    )
                    self._stop_event.set()
            else:
                # Unknown live_status value — treat as unknown.
                self._consecutive_failures += 1
                log.warning("Unknown live_status value: %s", live_status)
                self._state.record_live_check(LiveCheckStatus.UNKNOWN.value)
                self._save_fn(self._state)
