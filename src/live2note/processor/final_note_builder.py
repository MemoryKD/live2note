"""Build a FinalNote data structure from chunks, summaries, and task metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FinalNote:
    title: str = ""
    platform: str = ""
    streamer: str = ""
    stream_title: str = ""
    source_url: str = ""
    started_at: str = ""
    ended_at: str = ""
    task_id: str = ""
    tags: list[str] = field(default_factory=list)

    one_line_summary: str = ""
    key_points: list[str] = field(default_factory=list)
    knowledge_sections: list[dict[str, Any]] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)
    important_quotes: list[dict[str, Any]] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    timestamp_index: list[dict[str, Any]] = field(default_factory=list)
    follow_up_questions: list[str] = field(default_factory=list)


def build_final_note(
    task_id: str,
    metadata: dict[str, Any],
    chunks: list[dict[str, Any]],
    summaries: list[dict[str, Any]] | None,
) -> FinalNote:
    """Assemble a FinalNote from task data.

    If *summaries* is None or empty, sections that require LLM output
    will be marked as "未进行 LLM 总结".
    """
    note = FinalNote(
        task_id=task_id,
        platform=metadata.get("platform", ""),
        streamer=metadata.get("streamer", ""),
        stream_title=metadata.get("title", ""),
        source_url=metadata.get("url", ""),
        started_at=metadata.get("started_at") or "",
        ended_at=metadata.get("ended_at") or "",
        title=metadata.get("title") or f"直播知识笔记 — {task_id}",
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


def _generate_questions(key_points: list[str], chunks: list[dict[str, Any]]) -> list[str]:
    """Generate follow-up questions based on key points."""
    if not key_points or key_points == ["未进行 LLM 总结"]:
        return ["未进行 LLM 总结，无法生成追问问题"]

    questions: list[str] = []
    for _i, kp in enumerate(key_points[:5]):
        questions.append(f"关于「{kp[:30]}」，能否展开讲讲具体案例？")
    return questions or ["未提取到足够信息生成追问问题"]
