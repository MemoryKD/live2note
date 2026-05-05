"""Assign diarization speaker labels to whisper transcript segments.

The assigner matches each whisper segment to the diarization segment
with the greatest temporal overlap.
"""

from __future__ import annotations

from live2note.transcriber.diarization.pyannote_backend import DiarizationSegment
from live2note.transcriber.whisper_engine import Segment


def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    """Compute the overlap duration between two time intervals."""
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def assign_speakers(
    whisper_segments: list[Segment],
    diarization_segments: list[DiarizationSegment],
) -> list[Segment]:
    """Assign speaker labels to whisper segments based on temporal overlap.

    For each whisper segment, the diarization segment with the greatest
    overlap duration wins. If no overlap is found (should not happen with
    real diarization), the speaker label remains empty.

    Args:
        whisper_segments: List of transcribed segments (from WhisperEngine).
        diarization_segments: List of diarized speaker segments.

    Returns:
        New list of Segment objects with speaker field populated.
    """
    if not diarization_segments:
        return whisper_segments

    result: list[Segment] = []

    for ws in whisper_segments:
        best_speaker = ""
        best_overlap = 0.0

        for ds in diarization_segments:
            o = _overlap(ws.start, ws.end, ds.start, ds.end)
            if o > best_overlap:
                best_overlap = o
                best_speaker = ds.speaker

        result.append(
            Segment(
                start=ws.start,
                end=ws.end,
                text=ws.text,
                confidence=ws.confidence,
                speaker=best_speaker,
            )
        )

    return result


def collect_speaker_segments(
    whisper_segments: list[Segment],
) -> dict[str, list[dict[str, float | str]]]:
    """Group whisper segments by speaker for summary.

    Returns:
        Dict mapping speaker label -> list of {start, end, text} entries.
    """
    speaker_map: dict[str, list[dict[str, float | str]]] = {}
    for seg in whisper_segments:
        spk = seg.speaker or "UNKNOWN"
        if spk not in speaker_map:
            speaker_map[spk] = []
        speaker_map[spk].append({
            "start": seg.start,
            "end": seg.end,
            "text": seg.text,
        })
    return speaker_map
