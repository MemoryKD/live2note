"""Task state, metadata, and live stream info models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Enums ───────────────────────────────────────────────────


class TaskStatus(str, Enum):
    CREATED = "CREATED"
    CHECKING = "CHECKING"
    WAITING_LIVE = "WAITING_LIVE"
    RECORDING = "RECORDING"
    STOP_REQUESTED = "STOP_REQUESTED"
    STOPPING = "STOPPING"
    LIVE_ENDED = "LIVE_ENDED"
    FINALIZING = "FINALIZING"
    TRANSCRIBING = "TRANSCRIBING"
    PROCESSING = "PROCESSING"
    SUMMARIZING = "SUMMARIZING"
    SAVING = "SAVING"
    IMPORTING_GETNOTE = "IMPORTING_GETNOTE"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_MANUAL_STOP = "COMPLETED_WITH_MANUAL_STOP"
    FAILED = "FAILED"
    STOPPED = "STOPPED"


class StopReason(str, Enum):
    LIVE_ENDED = "live_ended"
    MANUAL_STOP = "manual_stop"
    STREAM_ERROR = "stream_error"
    NO_DATA_TIMEOUT = "no_data_timeout"
    USER_KEYBOARD_INTERRUPT = "user_keyboard_interrupt"
    UNKNOWN = "unknown"


PIPELINE_STEPS: list[str] = [
    "check",
    "record",
    "transcribe",
    "process",
    "summarize",
    "save",
    "import_getnote",
]

STEP_TO_STATUS: dict[str, TaskStatus] = {
    "check": TaskStatus.CHECKING,
    "record": TaskStatus.RECORDING,
    "transcribe": TaskStatus.TRANSCRIBING,
    "process": TaskStatus.PROCESSING,
    "summarize": TaskStatus.SUMMARIZING,
    "save": TaskStatus.SAVING,
    "import_getnote": TaskStatus.IMPORTING_GETNOTE,
}


# ── Check result (returned by platform adapters) ────────────


@dataclass(frozen=True)
class CheckResult:
    """Unified result from an adapter's check_live call."""

    platform: str
    is_live: bool
    title: str = ""
    streamer: str = ""
    stream_url: str = ""
    room_id: str = ""
    cover_url: str = ""
    started_at: str | None = None
    error: str | None = None


# ── Live stream info (legacy, kept for compat) ──────────────


@dataclass(frozen=True)
class LiveInfo:
    platform: str
    room_id: str
    title: str
    streamer: str
    stream_url: str
    is_live: bool
    started_at: str | None = None
    cover_url: str | None = None


# ── Metadata ────────────────────────────────────────────────


@dataclass
class TaskMetadata:
    platform: str = ""
    room_id: str = ""
    streamer: str = ""
    title: str = ""
    started_at: str | None = None
    ended_at: str | None = None
    url: str = ""
    stream_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "room_id": self.room_id,
            "streamer": self.streamer,
            "title": self.title,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "url": self.url,
            "stream_url": self.stream_url,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskMetadata:
        known = {k for k in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


# ── Audio segment record ───────────────────────────────────


@dataclass
class AudioSegment:
    index: int
    file: str
    duration: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"index": self.index, "file": self.file, "duration": self.duration}


# ── Task state ──────────────────────────────────────────────


@dataclass
class TaskState:
    task_id: str
    url: str
    platform: str = "auto"
    source_type: str = ""
    status: str = TaskStatus.CREATED.value
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    started_at: str | None = None
    ended_at: str | None = None
    current_step: str | None = None
    finished_steps: list[str] = field(default_factory=list)
    audio_segments: list[dict[str, Any]] = field(default_factory=list)
    transcripts: list[dict[str, Any]] = field(default_factory=list)
    summaries: list[dict[str, Any]] = field(default_factory=list)
    final_note_path: str | None = None
    getnote_enabled: bool = False
    getnote_imported: bool = False
    getnote_import_time: str | None = None
    getnote_error: str | None = None
    getnote_tags: list[str] = field(default_factory=list)
    error_message: str | None = None
    retry_count: int = 0
    duration: int = 0
    pid: int | None = None
    ffmpeg_pid: int | None = None
    stop_requested: bool = False
    stop_reason: str | None = None
    stop_requested_at: str | None = None
    stopped_at: str | None = None
    last_segment_at: str | None = None
    last_stream_check_at: str | None = None
    live_status: str = "unknown"
    metadata: TaskMetadata = field(default_factory=TaskMetadata)

    # ── helpers ──────────────────────────────────────────────

    def touch(self) -> None:
        self.updated_at = _now_iso()

    def set_status(self, status: TaskStatus) -> None:
        self.status = status.value
        self.touch()

    def set_step(self, step: str) -> None:
        self.current_step = step
        if step in STEP_TO_STATUS:
            self.status = STEP_TO_STATUS[step].value
        self.touch()

    def mark_started(self) -> None:
        if self.started_at is None:
            self.started_at = _now_iso()
        self.touch()

    def mark_completed(self) -> None:
        self.status = TaskStatus.COMPLETED.value
        self.current_step = None
        self.ended_at = _now_iso()
        self.touch()

    def mark_failed(self, message: str) -> None:
        self.status = TaskStatus.FAILED.value
        self.error_message = message
        self.ended_at = _now_iso()
        self.touch()

    def mark_stopped(self, reason: str = StopReason.UNKNOWN.value) -> None:
        self.status = TaskStatus.STOPPED.value
        self.stop_reason = reason
        self.stopped_at = _now_iso()
        self.ended_at = _now_iso()
        self.stop_requested = False
        self.touch()

    def request_stop(self, reason: str = StopReason.MANUAL_STOP.value) -> None:
        self.stop_requested = True
        self.stop_reason = reason
        self.stop_requested_at = _now_iso()
        if self.status == TaskStatus.RECORDING.value:
            self.status = TaskStatus.STOP_REQUESTED.value
        self.touch()

    def mark_finalizing(self) -> None:
        self.status = TaskStatus.FINALIZING.value
        self.touch()

    def mark_completed_with_stop(self) -> None:
        self.status = TaskStatus.COMPLETED_WITH_MANUAL_STOP.value
        self.current_step = None
        self.ended_at = _now_iso()
        self.stop_requested = False
        self.touch()

    def is_stop_requested(self) -> bool:
        return self.stop_requested

    def record_segment_time(self) -> None:
        self.last_segment_at = _now_iso()
        self.touch()

    def record_stream_check(self, is_live: bool) -> None:
        self.last_stream_check_at = _now_iso()
        self.live_status = "live" if is_live else "ended"
        self.touch()

    def finish_step(self, step: str) -> None:
        if step not in self.finished_steps:
            self.finished_steps.append(step)
        self.touch()

    def is_step_done(self, step: str) -> bool:
        return step in self.finished_steps

    def next_step(self) -> str | None:
        for step in PIPELINE_STEPS:
            if step not in self.finished_steps:
                return step
        return None

    def add_audio_segment(self, index: int, file: str, duration: float = 0.0) -> None:
        self.audio_segments.append(
            {"index": index, "file": file, "duration": duration}
        )
        self.touch()

    def add_transcript(self, index: int, file: str) -> None:
        self.transcripts.append({"index": index, "file": file})
        self.touch()

    def has_transcript(self, segment_index: int) -> bool:
        return any(t.get("index") == segment_index for t in self.transcripts)

    def add_summary(self, chunk_index: int, file: str) -> None:
        self.summaries.append({"chunk_index": chunk_index, "file": file})
        self.touch()

    # ── serialization ────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "url": self.url,
            "platform": self.platform,
            "source_type": self.source_type,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "current_step": self.current_step,
            "finished_steps": list(self.finished_steps),
            "audio_segments": list(self.audio_segments),
            "transcripts": list(self.transcripts),
            "summaries": list(self.summaries),
            "final_note_path": self.final_note_path,
            "getnote_enabled": self.getnote_enabled,
            "getnote_imported": self.getnote_imported,
            "getnote_import_time": self.getnote_import_time,
            "getnote_error": self.getnote_error,
            "getnote_tags": list(self.getnote_tags),
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "duration": self.duration,
            "pid": self.pid,
            "ffmpeg_pid": self.ffmpeg_pid,
            "stop_requested": self.stop_requested,
            "stop_reason": self.stop_reason,
            "stop_requested_at": self.stop_requested_at,
            "stopped_at": self.stopped_at,
            "last_segment_at": self.last_segment_at,
            "last_stream_check_at": self.last_stream_check_at,
            "live_status": self.live_status,
            "metadata": self.metadata.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskState:
        meta = TaskMetadata.from_dict(data.get("metadata", {}))
        return cls(
            task_id=data["task_id"],
            url=data["url"],
            platform=data.get("platform", "auto"),
            source_type=data.get("source_type", ""),
            status=data.get("status", TaskStatus.CREATED.value),
            created_at=data.get("created_at", _now_iso()),
            updated_at=data.get("updated_at", _now_iso()),
            started_at=data.get("started_at"),
            ended_at=data.get("ended_at"),
            current_step=data.get("current_step"),
            finished_steps=data.get("finished_steps", []),
            audio_segments=data.get("audio_segments", []),
            transcripts=data.get("transcripts", []),
            summaries=data.get("summaries", []),
            final_note_path=data.get("final_note_path"),
            getnote_enabled=data.get("getnote_enabled", False),
            getnote_imported=data.get("getnote_imported", False),
            getnote_import_time=data.get("getnote_import_time"),
            getnote_error=data.get("getnote_error"),
            getnote_tags=data.get("getnote_tags", []),
            error_message=data.get("error_message"),
            retry_count=data.get("retry_count", 0),
            duration=data.get("duration", 0),
            pid=data.get("pid"),
            ffmpeg_pid=data.get("ffmpeg_pid"),
            stop_requested=data.get("stop_requested", False),
            stop_reason=data.get("stop_reason"),
            stop_requested_at=data.get("stop_requested_at"),
            stopped_at=data.get("stopped_at"),
            last_segment_at=data.get("last_segment_at"),
            last_stream_check_at=data.get("last_stream_check_at"),
            live_status=data.get("live_status", "unknown"),
            metadata=meta,
        )
