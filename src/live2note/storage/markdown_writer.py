"""Write FinalNote as a structured Markdown document."""

from __future__ import annotations

from pathlib import Path

from live2note.processor.final_note_builder import FinalNote


def _fmt_ts(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    seconds = float(seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def write_final_markdown(note: FinalNote, output_path: Path) -> None:
    """Render the final note as Markdown and write to *output_path*."""
    lines: list[str] = []

    # Title.
    lines.append(f"# {note.title}")
    lines.append("")

    # Basic info.
    lines.append("## 基本信息")
    lines.append(f"- 平台：{note.platform or '-'}")
    lines.append(f"- 主播：{note.streamer or '-'}")
    lines.append(f"- 直播标题：{note.stream_title or '-'}")
    lines.append(f"- 来源链接：{note.source_url or '-'}")
    lines.append(f"- 开始时间：{note.started_at or '-'}")
    lines.append(f"- 结束时间：{note.ended_at or '-'}")
    lines.append(f"- 任务 ID：{note.task_id}")
    lines.append(f"- 标签：{', '.join(note.tags)}")
    lines.append("")

    # Speaker info.
    if note.speaker_info:
        lines.append("## 说话人")
        lines.append("")
        for spk in note.speaker_info:
            count = spk.get("segment_count", 0)
            lines.append(f"- **{spk['speaker']}**: 发言 {count} 次")
        lines.append("")

    # One-line summary.
    lines.append("## 一句话总结")
    lines.append("")
    lines.append(note.one_line_summary)
    lines.append("")

    # Key points.
    lines.append("## 核心观点")
    lines.append("")
    for i, kp in enumerate(note.key_points, 1):
        lines.append(f"{i}. {kp}")
    lines.append("")

    # Knowledge by topic.
    lines.append("## 主题化知识整理")
    lines.append("")
    for section in note.knowledge_sections:
        lines.append(f"### {section['topic']}")
        lines.append("")
        for pt in section.get("points", []):
            lines.append(f"- {pt}")
        lines.append("")

    # Action items.
    lines.append("## 可执行建议")
    lines.append("")
    for i, ai in enumerate(note.action_items, 1):
        lines.append(f"{i}. {ai}")
    lines.append("")

    # Important quotes index.
    lines.append("## 重要观点索引")
    lines.append("")
    if note.important_quotes:
        for q in note.important_quotes:
            ts = _fmt_ts(q.get("start"))
            lines.append(f"- [{ts}] {q['text']}")
    else:
        lines.append("- (无)")
    lines.append("")

    # Original text excerpts.
    lines.append("## 原文重要片段")
    lines.append("")
    if note.important_quotes:
        for q in note.important_quotes:
            ts = _fmt_ts(q.get("start"))
            lines.append(f"> **[{ts}]** {q['text']}")
            lines.append("")
    else:
        lines.append("- (无)")
    lines.append("")

    # Keywords.
    lines.append("## 检索关键词")
    lines.append("")
    if note.keywords:
        lines.append(" ".join(f"`{kw}`" for kw in note.keywords))
    else:
        lines.append("- (无)")
    lines.append("")

    # Timestamp index.
    lines.append("## 时间戳索引")
    lines.append("")
    for entry in note.timestamp_index:
        ts_start = _fmt_ts(entry.get("start"))
        ts_end = _fmt_ts(entry.get("end"))
        summary_preview = entry.get("summary", "")[:60]
        if summary_preview:
            lines.append(f"- [{ts_start} - {ts_end}] {summary_preview}")
        else:
            lines.append(f"- [{ts_start} - {ts_end}]")
    lines.append("")

    # Follow-up questions.
    lines.append("## 后续可追问的问题")
    lines.append("")
    for i, q in enumerate(note.follow_up_questions, 1):
        lines.append(f"{i}. {q}")
    lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
