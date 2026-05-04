"""Pipeline executor — runs the live2note processing steps sequentially.

Each step checks state.is_step_done() before executing, so re-running
the pipeline safely skips completed work (checkpoint resume).
"""

from __future__ import annotations

import json
from pathlib import Path

from live2note.config import AppConfig
from live2note.logger import get_logger
from live2note.models.task import TaskState
from live2note.task_manager import TaskManager

log = get_logger("pipeline")


class Pipeline:
    """Executes the live2note processing steps in order.

    Steps:
      check → record → transcribe → process → summarize → save → import_getnote

    'check' and 'record' are handled externally by the CLI (they need
    adapter/stream context). This pipeline handles transcribe..import_getnote.
    """

    def __init__(self, mgr: TaskManager, cfg: AppConfig) -> None:
        self._mgr = mgr
        self._cfg = cfg

    def run(self, state: TaskState, stop_reason: str | None = None) -> TaskState:
        """Execute all remaining pipeline steps. Returns final state.

        Args:
            state: Current task state.
            stop_reason: If set, task was stopped — mark appropriate final status.
        """
        task_dir = self._mgr.base_dir / state.task_id

        state.mark_finalizing()
        self._mgr.save(state)

        steps = [
            ("transcribe", self._step_transcribe),
            ("process", self._step_process),
            ("save", self._step_save),
        ]

        for step_name, step_fn in steps:
            if state.is_step_done(step_name):
                log.info("Step %s: already done, skipping.", step_name)
                continue

            log.info("Step %s: starting.", step_name)
            try:
                state = step_fn(state, task_dir)
            except Exception as exc:
                log.error("Step %s failed: %s", step_name, exc, exc_info=True)
                state.mark_failed(f"{step_name}: {exc}")
                self._mgr.save(state)
                return state

        # Set final status.
        from live2note.models.task import StopReason

        if stop_reason == StopReason.MANUAL_STOP.value:
            state.mark_completed_with_stop()
            log.info("Task completed with manual stop.")
        else:
            state.mark_completed()
            log.info("Task completed.")

        self._mgr.save(state)
        return state

    # ── step: transcribe ─────────────────────────────────────

    def _step_transcribe(self, state: TaskState, task_dir: Path) -> TaskState:
        from live2note.transcriber import (
            WhisperEngine,
            write_transcript_json,
            write_transcript_markdown,
        )

        if not state.audio_segments:
            raise RuntimeError("No audio segments to transcribe.")

        state.set_step("transcribe")
        self._mgr.save(state)

        engine = WhisperEngine(
            model_size=self._cfg.transcription.model_size,
            language=self._cfg.transcription.language,
            device=self._cfg.transcription.device,
            compute_type=self._cfg.transcription.compute_type,
            beam_size=self._cfg.transcription.beam_size,
            vad_filter=self._cfg.transcription.vad_filter,
        )

        transcripts_dir = task_dir / "transcripts"
        global_offset = 0.0
        completed = 0
        failed = 0

        for seg_info in state.audio_segments:
            idx = seg_info["index"]
            audio_file = seg_info["file"]
            seg_duration = float(seg_info.get("duration", 0))

            audio_path = Path(audio_file)
            if not audio_path.is_absolute():
                audio_path = task_dir / audio_path

            if state.has_transcript(idx):
                global_offset += seg_duration
                continue

            if not audio_path.is_file():
                log.warning("Segment %03d: file not found: %s", idx, audio_path)
                failed += 1
                global_offset += seg_duration
                continue

            try:
                segments = engine.transcribe(audio_path)
            except Exception as exc:
                log.error("Segment %03d transcription failed: %s", idx, exc)
                failed += 1
                global_offset += seg_duration
                continue

            stem = f"segment_{idx:03d}"
            json_path = transcripts_dir / f"{stem}.json"
            md_path = transcripts_dir / f"{stem}.md"

            write_transcript_json(json_path, idx, audio_path.name, segments, global_offset)
            write_transcript_markdown(md_path, idx, audio_path.name, segments, global_offset)

            state.add_transcript(idx, str(json_path))
            self._mgr.save(state)
            completed += 1
            global_offset += seg_duration

        if failed > 0 and completed == 0:
            raise RuntimeError(f"All {failed} segment(s) failed to transcribe.")

        state.finish_step("transcribe")
        self._mgr.save(state)
        log.info("Transcription: %d done, %d failed.", completed, failed)
        return state

    # ── step: process (clean + chunk + summarize) ─────────────

    def _step_process(self, state: TaskState, task_dir: Path) -> TaskState:
        from live2note.processor.chunker import chunk_segments
        from live2note.processor.cleaner import CleanSegment, clean_segments

        transcripts_dir = task_dir / "transcripts"
        transcript_files = sorted(transcripts_dir.glob("segment_*.json"))
        if not transcript_files:
            raise RuntimeError("No transcript files found.")

        state.set_step("process")
        self._mgr.save(state)

        # Load all transcript segments.
        all_segments: list[CleanSegment] = []
        for tf in transcript_files:
            data = json.loads(tf.read_text(encoding="utf-8"))
            for seg in data.get("segments", []):
                all_segments.append(CleanSegment(
                    start=seg["global_start"],
                    end=seg["global_end"],
                    text=seg["text"],
                ))

        cleaned = clean_segments(all_segments)
        chunks = chunk_segments(cleaned)

        if not chunks:
            state.finish_step("process")
            self._mgr.save(state)
            return state

        # Save chunks.
        chunks_dir = task_dir / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)
        chunks_path = chunks_dir / "chunks.json"
        chunks_data = [
            {"chunk_id": c.chunk_id, "start": c.start, "end": c.end,
             "text": c.text, "source_segments": c.source_segments}
            for c in chunks
        ]
        chunks_path.write_text(
            json.dumps(chunks_data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        state.finish_step("process")
        self._mgr.save(state)

        # Summarize.
        self._step_summarize(state, task_dir, chunks)
        return state

    # ── step: summarize ──────────────────────────────────────

    def _step_summarize(self, state: TaskState, task_dir: Path, chunks) -> None:
        from live2note.processor.summarizer import Summarizer

        summarizer = Summarizer(
            api_base=self._cfg.llm.api_base,
            api_key=self._cfg.llm.api_key,
            model=self._cfg.llm.model,
            temperature=self._cfg.llm.temperature,
            max_tokens=self._cfg.llm.max_tokens,
            summary_model=self._cfg.llm.summary_model,
        )

        if not summarizer.is_configured:
            log.warning("LLM API key not configured — skipping summarization.")
            return

        summaries_dir = task_dir / "summaries"
        summaries_dir.mkdir(parents=True, exist_ok=True)

        state.set_step("summarize")
        self._mgr.save(state)

        summaries = []
        for chunk in chunks:
            log.info("Summarizing chunk %d/%d", chunk.chunk_id, len(chunks))
            try:
                summary = summarizer.summarize(chunk)
                summaries.append({
                    "chunk_id": summary.chunk_id,
                    "start": summary.start,
                    "end": summary.end,
                    "summary": summary.summary,
                    "key_points": summary.key_points,
                    "knowledge_points": summary.knowledge_points,
                    "action_items": summary.action_items,
                    "tags": summary.tags,
                    "keywords": summary.keywords,
                    "important_quotes": summary.important_quotes,
                })
            except Exception as exc:
                log.error("Chunk %d summarization failed: %s", chunk.chunk_id, exc)
                summaries.append({
                    "chunk_id": chunk.chunk_id, "start": chunk.start, "end": chunk.end,
                    "summary": f"[Error: {exc}]",
                    "key_points": [], "knowledge_points": [], "action_items": [],
                    "tags": [], "keywords": [], "important_quotes": [],
                })

        summaries_path = summaries_dir / "chunk_summaries.json"
        summaries_path.write_text(
            json.dumps(summaries, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        state.finish_step("summarize")
        self._mgr.save(state)

    # ── step: save (generate final note) ─────────────────────

    def _step_save(self, state: TaskState, task_dir: Path) -> TaskState:
        from live2note.processor.final_note_builder import build_final_note
        from live2note.storage import write_final_json, write_final_markdown

        chunks_path = task_dir / "chunks" / "chunks.json"
        if not chunks_path.is_file():
            raise RuntimeError("No chunks found — run 'process' first.")

        chunks = json.loads(chunks_path.read_text(encoding="utf-8"))

        summaries_path = task_dir / "summaries" / "chunk_summaries.json"
        summaries = None
        if summaries_path.is_file():
            summaries = json.loads(summaries_path.read_text(encoding="utf-8"))

        note = build_final_note(
            task_id=state.task_id,
            metadata=state.metadata.to_dict(),
            chunks=chunks,
            summaries=summaries,
        )

        notes_dir = task_dir / "notes"
        md_path = notes_dir / "final_note.md"
        json_path = notes_dir / "final_note.json"

        write_final_markdown(note, md_path)
        write_final_json(note, json_path)

        state.final_note_path = str(md_path)
        state.finish_step("save")
        self._mgr.save(state)

        # Auto-import to getnote if enabled.
        if self._cfg.getnote.enabled or state.getnote_enabled:
            self._step_import_getnote(state)

        return state

    # ── step: import getnote ─────────────────────────────────

    def _step_import_getnote(self, state: TaskState) -> None:
        from datetime import datetime, timezone

        from live2note.storage.getnote import import_to_getnote

        if state.getnote_imported:
            return

        if not state.final_note_path:
            return

        md_path = Path(state.final_note_path)
        if not md_path.is_file():
            return

        gn = self._cfg.getnote
        title = state.metadata.title or state.task_id
        tags = list(gn.default_tags) + list(state.getnote_tags)

        result = import_to_getnote(
            file_path=md_path,
            command_template=gn.command,
            title=title,
            tags=tags,
            timeout=gn.timeout,
        )

        state.getnote_import_time = datetime.now(timezone.utc).isoformat()

        if result.success:
            state.getnote_imported = True
            state.getnote_error = None
            state.finish_step("import_getnote")
            log.info("getnote import succeeded.")
        else:
            state.getnote_imported = False
            state.getnote_error = result.message
            log.warning("getnote import failed: %s", result.message)

        self._mgr.save(state)
