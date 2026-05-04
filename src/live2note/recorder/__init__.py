"""Audio recording modules."""

from live2note.recorder.ffmpeg_recorder import FfmpegRecorder
from live2note.recorder.live_monitor import LiveMonitor
from live2note.recorder.stop_controller import (
    is_stop_flag_present,
    read_stop_flag,
    remove_stop_flag,
    request_stop,
    stop_ffmpeg,
    write_stop_flag,
)
from live2note.recorder.stream_resolver import StreamResolver

__all__ = [
    "FfmpegRecorder",
    "LiveMonitor",
    "StreamResolver",
    "is_stop_flag_present",
    "read_stop_flag",
    "remove_stop_flag",
    "request_stop",
    "stop_ffmpeg",
    "write_stop_flag",
]
