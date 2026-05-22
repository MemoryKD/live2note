"""FFmpeg-based live stream recorder with time-based segment splitting.

Records a live audio stream using sequential ffmpeg processes.
Each segment is a standalone WAV file (16 kHz, mono, pcm_s16le).
Supports stop flags, no-data timeout, and auto-reconnect on ffmpeg failure.
"""

from __future__ import annotations

import signal
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from live2note.logger import get_logger
from live2note.recorder import stop_controller

log = get_logger("recorder.ffmpeg")

SegmentResult = dict[str, object]

# reconnect_fn(seg_index, attempt) -> new stream URL or None to abort
ReconnectFn = Callable[[int, int], str | None]


class FfmpegRecorder:
    """Records a live stream into numbered WAV segments.

    Supports:
    - Stop flag detection (control/stop.flag)
    - ffmpeg PID tracking
    - No-data timeout
    - Auto-reconnect on stream interruption
    """

    def __init__(
        self,
        ffmpeg_path: str = "ffmpeg",
        sample_rate: int = 16000,
        channels: int = 1,
    ) -> None:
        self._ffmpeg = ffmpeg_path
        self._sample_rate = sample_rate
        self._channels = channels
        self._stop_requested = False
        self._proc: subprocess.Popen | None = None
        self._last_ffmpeg_pid: int | None = None
        self._last_ffmpeg_exit_code: int | None = None
        self._last_ffmpeg_stderr: str | None = None

    @property
    def last_ffmpeg_pid(self) -> int | None:
        return self._last_ffmpeg_pid

    @property
    def last_ffmpeg_exit_code(self) -> int | None:
        return self._last_ffmpeg_exit_code

    @property
    def last_ffmpeg_stderr(self) -> str | None:
        return self._last_ffmpeg_stderr

    # ── public API ───────────────────────────────────────────

    def record(
        self,
        stream_url: str,
        output_dir: Path,
        segment_seconds: int = 300,
        total_seconds: int = 0,
        task_dir: Path | None = None,
        no_data_timeout: int = 0,
        reconnect_fn: ReconnectFn | None = None,
        max_reconnect_attempts: int = 20,
        reconnect_delay: int = 10,
    ) -> list[SegmentResult]:
        """Record the stream until stopped or total_seconds is reached.

        Args:
            stream_url:      Direct stream URL (m3u8/flv/rtmp/…).
            output_dir:      Directory for segment WAV files.
            segment_seconds: Duration of each segment (default 300 = 5 min).
            total_seconds:   Total recording limit (0 = unlimited).
            task_dir:        Task directory (for stop flag checking).
            no_data_timeout: Stop if no new segment within this many seconds.
            reconnect_fn:    Callable(seg_index, attempt) -> new URL or None to abort.
            max_reconnect_attempts: Max reconnect retries per segment.
            reconnect_delay: Seconds to wait between reconnect attempts.
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        segments: list[SegmentResult] = []
        seg_index = 1
        total_recorded = 0.0
        max_segments = (
            int(total_seconds / segment_seconds) + 1 if total_seconds > 0 else 0
        )
        last_segment_time = time.monotonic()

        while not self._stop_requested:
            # Check stop flag from disk (cross-process signal).
            if task_dir and stop_controller.is_stop_flag_present(task_dir):
                log.info("Stop flag detected — ending recording.")
                self._stop_requested = True
                break

            # No-data timeout.
            if no_data_timeout > 0 and seg_index > 1:
                elapsed_since_last = time.monotonic() - last_segment_time
                if elapsed_since_last > no_data_timeout:
                    log.warning(
                        "No new segment for %ds (timeout=%ds) — stopping.",
                        int(elapsed_since_last), no_data_timeout,
                    )
                    break

            if max_segments > 0 and seg_index > max_segments:
                log.info("Reached total duration limit (%ds).", total_seconds)
                break

            remaining = total_seconds - total_recorded if total_seconds > 0 else 0
            seg_dur = min(segment_seconds, remaining) if remaining > 0 else segment_seconds

            filename = f"segment_{seg_index:03d}.wav"
            output_path = output_dir / filename

            log.info("Recording segment %d -> %s (%ds)", seg_index, filename, int(seg_dur))

            current_stream_url = stream_url
            result = self._record_one(current_stream_url, output_path, seg_dur)

            if result is not None:
                segments.append(result)
                total_recorded += float(result["duration"])
                last_segment_time = time.monotonic()
                log.info("Segment %d complete: %.1fs", seg_index, result["duration"])
                seg_index += 1
                continue

            # ── Segment failed — reconnect? ──────────────────────────────────
            if self._stop_requested:
                log.info("Recording stopped by user.")
                break

            if reconnect_fn is None or max_reconnect_attempts <= 0:
                log.warning("Segment %d failed — stream may have ended.", seg_index)
                break

            log.warning(
                "Segment %d failed — starting reconnect (max %d attempts)...",
                seg_index, max_reconnect_attempts,
            )
            reconnected = False
            for attempt in range(1, max_reconnect_attempts + 1):
                if self._stop_requested:
                    break
                time.sleep(reconnect_delay)
                new_url = reconnect_fn(seg_index, attempt)
                if new_url is None:
                    log.warning("Reconnect aborted by caller (attempt %d/%d).",
                                attempt, max_reconnect_attempts)
                    break
                log.info("Retrying segment %d with fresh URL (attempt %d/%d)",
                         seg_index, attempt, max_reconnect_attempts)
                result = self._record_one(new_url, output_path, seg_dur)
                if result is not None:
                    segments.append(result)
                    total_recorded += float(result["duration"])
                    last_segment_time = time.monotonic()
                    log.info("Segment %d complete after reconnect: %.1fs",
                             seg_index, result["duration"])
                    reconnected = True
                    seg_index += 1
                    break

            if reconnected:
                continue

            if self._stop_requested:
                log.info("Recording stopped by user during reconnect.")
            else:
                log.warning("All %d reconnect attempts failed — ending recording.",
                            max_reconnect_attempts)
            break

        return segments

    def stop(self) -> None:
        self._stop_requested = True
        if self._proc and self._proc.poll() is None:
            self._terminate_ffmpeg()

    @property
    def stop_requested(self) -> bool:
        return self._stop_requested

    # ── single-segment recorder ──────────────────────────────

    def _record_one(
        self,
        stream_url: str,
        output_path: Path,
        duration: float,
    ) -> SegmentResult | None:
        cmd = self._build_command(stream_url, output_path, duration)
        log.debug("ffmpeg command: %s", " ".join(cmd))

        returncode: int | None = None
        stderr_bytes = b""
        t0 = time.monotonic()
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            self._last_ffmpeg_pid = self._proc.pid
            log.info("ffmpeg started pid=%d", self._proc.pid)
            _, stderr_bytes = self._proc.communicate()
            returncode = self._proc.returncode
            elapsed = time.monotonic() - t0
        except KeyboardInterrupt:
            log.info("Ctrl+C received — stopping recording...")
            self._stop_requested = True
            self._terminate_ffmpeg()
            elapsed = time.monotonic() - t0
        except FileNotFoundError:
            log.error("ffmpeg not found at '%s'. Is it installed?", self._ffmpeg)
            raise
        finally:
            self._proc = None
            self._last_ffmpeg_exit_code = returncode
            if stderr_bytes:
                self._last_ffmpeg_stderr = stderr_bytes.decode("utf-8", errors="replace")[-300:]

        if self._stop_requested:
            if output_path.is_file() and output_path.stat().st_size > 0:
                return {
                    "index": 0,
                    "file": str(output_path),
                    "duration": round(elapsed, 1),
                }
            return None

        if returncode is not None and returncode != 0:
            err = stderr_bytes.decode("utf-8", errors="replace")[-300:]
            log.error("ffmpeg exited with code %d: %s", returncode, err)
            return None

        if not output_path.is_file():
            log.error("ffmpeg completed but output file missing: %s", output_path)
            return None

        return {
            "index": 0,
            "file": str(output_path),
            "duration": round(elapsed, 1),
        }

    # ── command builder ──────────────────────────────────────

    def _build_command(
        self, stream_url: str, output_path: Path, duration: float
    ) -> list[str]:
        return [
            self._ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel", "warning",
            "-user_agent", "Mozilla/5.0",
            "-i", stream_url,
            "-t", str(int(duration)),
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", str(self._sample_rate),
            "-ac", str(self._channels),
            str(output_path),
        ]

    # ── process cleanup ──────────────────────────────────────

    def _terminate_ffmpeg(self) -> None:
        if self._proc is None or self._proc.poll() is not None:
            return
        try:
            if hasattr(signal, "CTRL_C_EVENT"):
                self._proc.send_signal(signal.CTRL_C_EVENT)
            else:
                self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                log.warning("ffmpeg did not exit in time, killing.")
                self._proc.kill()
                self._proc.wait(timeout=5)
        except OSError:
            pass
