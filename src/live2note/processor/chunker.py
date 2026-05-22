"""Split cleaned transcript segments into size-bounded chunks."""

from __future__ import annotations

from dataclasses import dataclass, field

from live2note.logger import get_logger
from live2note.processor.cleaner import CleanSegment

log = get_logger("processor.chunker")

# Target chunk size in Chinese characters (≈ bytes / 3 for UTF-8 CJK).
MIN_CHUNK_CHARS = 800
MAX_CHUNK_CHARS = 1500


@dataclass
class Chunk:
    chunk_id: int
    start: float
    end: float
    text: str
    source_segments: list[dict[str, float]] = field(default_factory=list)


def chunk_segments(
    segments: list[CleanSegment],
    min_chars: int = MIN_CHUNK_CHARS,
    max_chars: int = MAX_CHUNK_CHARS,
) -> list[Chunk]:
    """Group consecutive segments into chunks of *min_chars*–*max_chars* characters.

    Each chunk carries:
      - chunk_id   : 1-based index
      - start / end: wall-clock seconds from the original recording
      - text       : concatenated (and cleaned) segment texts
      - source_segments: list of {start, end} for traceability
    """
    if not segments:
        return []

    chunks: list[Chunk] = []
    buf_texts: list[str] = []
    buf_sources: list[dict[str, float]] = []
    buf_len = 0
    chunk_start = segments[0].start

    def flush() -> None:
        nonlocal buf_len, chunk_start
        if not buf_texts:
            return
        chunks.append(
            Chunk(
                chunk_id=len(chunks) + 1,
                start=chunk_start,
                end=buf_sources[-1]["end"],
                text="".join(buf_texts),
                source_segments=list(buf_sources),
            )
        )
        buf_texts.clear()
        buf_sources.clear()
        buf_len = 0

    for seg in segments:
        seg_text = seg.text
        seg_len = len(seg_text)

        # Start a new chunk buffer if empty.
        if not buf_texts:
            chunk_start = seg.start

        # If adding this segment would exceed max, flush first.
        if buf_len + seg_len > max_chars and buf_len > 0:
            flush()
            chunk_start = seg.start

        if seg_len > max_chars:
            log.warning(
                "Single segment exceeds max_chars (%d > %d), chunk may be oversized.",
                seg_len, max_chars,
            )

        buf_texts.append(seg_text)
        buf_sources.append({"start": seg.start, "end": seg.end})
        buf_len += seg_len

    flush()
    return chunks
