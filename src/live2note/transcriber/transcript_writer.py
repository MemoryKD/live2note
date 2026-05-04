"""Write transcription output as JSON and Markdown files."""

from __future__ import annotations

import json
from pathlib import Path

from live2note.transcriber.whisper_engine import Segment


def _fmt_ts(seconds: float) -> str:
    """Format seconds as HH:MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def write_transcript_json(
    output_path: Path,
    segment_id: int,
    audio_file: str,
    segments: list[Segment],
    global_offset: float = 0.0,
) -> None:
    """Write structured transcript JSON.

    Each segment entry includes both local (within the audio file) and
    global (relative to the start of the full recording) timestamps.
    """
    entries = []
    for seg in segments:
        entries.append({
            "start": seg.start,
            "end": seg.end,
            "global_start": round(seg.start + global_offset, 3),
            "global_end": round(seg.end + global_offset, 3),
            "text": seg.text,
            "confidence": seg.confidence,
        })

    data = {
        "segment_id": segment_id,
        "audio_file": audio_file,
        "global_offset": global_offset,
        "segment_count": len(entries),
        "segments": entries,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def write_transcript_markdown(
    output_path: Path,
    segment_id: int,
    audio_file: str,
    segments: list[Segment],
    global_offset: float = 0.0,
) -> None:
    """Write a human-readable Markdown transcript with timestamps."""
    lines = [
        f"# Segment {segment_id:03d} Transcript",
        "",
        f"- Audio: `{audio_file}`",
        f"- Segment start: {_fmt_ts(global_offset)}",
        f"- Duration: {_fmt_ts(segments[-1].end) if segments else '00:00'}",
        f"- Segments: {len(segments)}",
        "",
        "---",
        "",
    ]

    for seg in segments:
        ts = _fmt_ts(seg.start + global_offset)
        lines.append(f"**[{ts}]** {seg.text}")
        lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
