"""Write FinalNote as a JSON document."""

from __future__ import annotations

import json
from pathlib import Path

from live2note.processor.final_note_builder import FinalNote


def write_final_json(note: FinalNote, output_path: Path) -> None:
    """Serialize the final note to JSON and write to *output_path*."""
    data = {
        "title": note.title,
        "task_id": note.task_id,
        "platform": note.platform,
        "streamer": note.streamer,
        "stream_title": note.stream_title,
        "source_url": note.source_url,
        "started_at": note.started_at,
        "ended_at": note.ended_at,
        "tags": note.tags,
        "one_line_summary": note.one_line_summary,
        "key_points": note.key_points,
        "knowledge_sections": note.knowledge_sections,
        "action_items": note.action_items,
        "important_quotes": note.important_quotes,
        "keywords": note.keywords,
        "timestamp_index": note.timestamp_index,
        "follow_up_questions": note.follow_up_questions,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
