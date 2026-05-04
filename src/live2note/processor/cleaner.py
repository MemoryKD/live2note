"""Clean transcript text: remove filler words, merge duplicates, preserve meaning."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class CleanSegment:
    start: float
    end: float
    text: str


# Chinese filler words / phrases — match and remove, keeping one trailing space.
_FILLER_RE = re.compile(
    r"(?:嗯+|啊+|呃+|额+|哦+|噢+|这个|那个|就是说|然后呢|对吧|是不是|"
    r"你知道吗|怎么说呢|反正就是|基本上|其实吧|说实话|我觉得吧)"
    r"[\s,，]*",
    re.UNICODE,
)

# Repeated punctuation collapse.
_MULTI_PUNCT_RE = re.compile(r"([，。！？,\.!?]){2,}")

# Collapse repeated adjacent sentences.
_DUP_SENTENCE_RE = re.compile(r"(.{4,}?)[。！？\.\!\?]\s*\1[。！？\.\!\?]")


def clean_segments(segments: list[CleanSegment]) -> list[CleanSegment]:
    """Clean a list of transcript segments in-place style (returns new list).

    Steps:
      1. Strip filler words from each segment.
      2. Collapse repeated punctuation.
      3. Remove exact-duplicate consecutive segments.
      4. Drop empty segments.
    """
    cleaned: list[CleanSegment] = []
    prev_text = ""

    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue

        text = _FILLER_RE.sub("", text)
        text = _MULTI_PUNCT_RE.sub(r"\1", text)
        text = _DUP_SENTENCE_RE.sub(r"\1。", text)
        text = text.strip()

        if not text:
            continue

        # Skip if identical to previous segment.
        if text == prev_text:
            # Extend previous segment's end time instead.
            if cleaned:
                cleaned[-1] = CleanSegment(
                    start=cleaned[-1].start,
                    end=seg.end,
                    text=cleaned[-1].text,
                )
            continue

        cleaned.append(CleanSegment(start=seg.start, end=seg.end, text=text))
        prev_text = text

    return cleaned
