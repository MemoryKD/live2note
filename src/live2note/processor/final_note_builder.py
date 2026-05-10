"""Build a FinalNote data structure from chunks, summaries, and task metadata."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class FinalNote:
    title: str = ""
    display_title: str = ""
    platform: str = ""
    streamer: str = ""
    author: str = ""
    stream_title: str = ""
    source_url: str = ""
    started_at: str = ""
    ended_at: str = ""
    task_id: str = ""
    tags: list[str] = field(default_factory=list)
    stop_reason: str = ""
    duration: str = ""

    one_line_summary: str = ""
    key_points: list[str] = field(default_factory=list)
    knowledge_sections: list[dict[str, Any]] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)
    important_quotes: list[dict[str, Any]] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    timestamp_index: list[dict[str, Any]] = field(default_factory=list)
    follow_up_questions: list[str] = field(default_factory=list)
    speaker_info: list[dict[str, Any]] = field(default_factory=list)


def _platform_display_name(platform: str) -> str:
    return {"douyin": "抖音", "bilibili": "B站", "generic": "通用直播流"}.get(
        platform, platform
    )


def build_final_note(
    task_id: str,
    metadata: dict[str, Any],
    chunks: list[dict[str, Any]],
    summaries: list[dict[str, Any]] | None,
    task_dir: Path | str | None = None,
    stop_reason: str = "",
) -> FinalNote:
    """Assemble a FinalNote from task data.

    If *summaries* is None or empty, sections that require LLM output
    will be marked as "未进行 LLM 总结".
    """
    platform_key = metadata.get("platform", "")
    platform_display = _platform_display_name(platform_key)
    author_val = metadata.get("author") or metadata.get("streamer") or "未知主播"
    stream_title = metadata.get("title") or "直播"
    display_title = metadata.get("display_title") or (
        f"{platform_display}直播知识笔记：{author_val} - {stream_title}"
    )

    note = FinalNote(
        task_id=task_id,
        platform=platform_key,
        streamer=metadata.get("streamer", ""),
        author=author_val,
        stream_title=stream_title,
        source_url=metadata.get("source_url") or metadata.get("url", ""),
        started_at=metadata.get("started_at") or "",
        ended_at=metadata.get("ended_at") or "",
        title=display_title,
        display_title=display_title,
        stop_reason=stop_reason,
    )

    # Build a lookup from chunk_id → summary.
    summary_map: dict[int, dict[str, Any]] = {}
    if summaries:
        for s in summaries:
            summary_map[s["chunk_id"]] = s

    # Collect all tags and keywords across chunks.
    all_tags: list[str] = []
    all_keywords: list[str] = []
    all_key_points: list[str] = []
    all_action_items: list[str] = []
    all_quotes: list[dict[str, Any]] = []
    all_knowledge: list[dict[str, Any]] = []
    one_line_parts: list[str] = []

    for chunk in chunks:
        cid = chunk["chunk_id"]
        summ = summary_map.get(cid)

        if summ:
            # One-line summary: concatenate chunk summaries.
            if summ.get("summary"):
                one_line_parts.append(summ["summary"])

            for kp in summ.get("key_points", []):
                if kp not in all_key_points:
                    all_key_points.append(kp)

            for ai in summ.get("action_items", []):
                if ai not in all_action_items:
                    all_action_items.append(ai)

            for t in summ.get("tags", []):
                if t not in all_tags:
                    all_tags.append(t)

            for kw in summ.get("keywords", []):
                if kw not in all_keywords:
                    all_keywords.append(kw)

            for q in summ.get("important_quotes", []):
                all_quotes.append({
                    "text": q,
                    "chunk_id": cid,
                    "start": chunk.get("start"),
                    "end": chunk.get("end"),
                })

            for kp in summ.get("knowledge_points", []):
                all_knowledge.append({
                    "point": kp,
                    "chunk_id": cid,
                    "start": chunk.get("start"),
                    "end": chunk.get("end"),
                })

        # Timestamp index: every chunk gets an entry.
        note.timestamp_index.append({
            "chunk_id": cid,
            "start": chunk.get("start"),
            "end": chunk.get("end"),
            "summary": summ.get("summary", "") if summ else "",
        })

    note.one_line_summary = " ".join(one_line_parts) if one_line_parts else "未进行 LLM 总结"
    note.key_points = all_key_points or ["未进行 LLM 总结"]
    note.action_items = all_action_items or ["未进行 LLM 总结"]
    note.tags = all_tags or ["live2note"]
    note.keywords = all_keywords
    note.important_quotes = all_quotes
    note.knowledge_sections = _group_by_topic(all_knowledge)
    note.follow_up_questions = _generate_questions(all_key_points, chunks)

    # Build speaker info from transcript files.
    if task_dir:
        note.speaker_info = _build_speaker_info(Path(task_dir))

    return note


def _group_by_topic(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group knowledge points by chunk as a simple topic proxy."""
    if not items:
        return [{"topic": "未进行 LLM 总结", "points": []}]

    by_chunk: dict[int, list[str]] = {}
    for item in items:
        cid = item["chunk_id"]
        by_chunk.setdefault(cid, []).append(item["point"])

    sections = []
    for cid, points in by_chunk.items():
        sections.append({
            "topic": f"主题 {cid}",
            "points": points,
        })
    return sections


def _build_speaker_info(task_dir: Path) -> list[dict[str, Any]]:
    """Extract speaker info from transcript JSON files."""
    transcripts_dir = task_dir / "transcripts"
    if not transcripts_dir.is_dir():
        return []

    speaker_data: dict[str, dict[str, Any]] = {}

    for tf in sorted(transcripts_dir.glob("segment_*.json")):
        try:
            data = json.loads(tf.read_text(encoding="utf-8"))
        except Exception:
            continue
        for seg in data.get("segments", []):
            spk = seg.get("speaker", "")
            if not spk:
                continue
            if spk not in speaker_data:
                speaker_data[spk] = {
                    "speaker": spk,
                    "first_seen": seg["global_start"],
                    "last_seen": seg["global_end"],
                    "segment_count": 0,
                }
            speaker_data[spk]["last_seen"] = seg["global_end"]
            speaker_data[spk]["segment_count"] += 1

    result = sorted(speaker_data.values(), key=lambda x: x["first_seen"])
    return result


def _generate_questions(key_points: list[str], chunks: list[dict[str, Any]]) -> list[str]:
    """Generate follow-up questions based on key points."""
    if not key_points or key_points == ["未进行 LLM 总结"]:
        return ["未进行 LLM 总结，无法生成追问问题"]

    questions: list[str] = []
    for _i, kp in enumerate(key_points[:5]):
        questions.append(f"关于「{kp[:30]}」，能否展开讲讲具体案例？")
    return questions or ["未提取到足够信息生成追问问题"]
