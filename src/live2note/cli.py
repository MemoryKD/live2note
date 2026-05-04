"""live2note CLI — Typer entry point."""

from __future__ import annotations

from pathlib import Path

import typer
from rich import print as rprint
from rich.panel import Panel
from rich.table import Table

from live2note import __version__
from live2note.config import AppConfig, config_summary, init_config, load_config
from live2note.logger import console, setup_logging
from live2note.models.task import TaskStatus
from live2note.task_manager import TaskManager

app = typer.Typer(
    name="live2note",
    help="Live stream knowledge capture agent — record, transcribe, organize, export.",
    add_completion=False,
)


def _get_manager(cfg: AppConfig) -> TaskManager:
    return TaskManager(cfg.output.base_dir)


def _status_style(status: str) -> str:
    mapping = {
        TaskStatus.CREATED.value: "[cyan]",
        TaskStatus.CHECKING.value: "[cyan]",
        TaskStatus.WAITING_LIVE.value: "[yellow]",
        TaskStatus.RECORDING.value: "[green]",
        TaskStatus.STOP_REQUESTED.value: "[yellow]",
        TaskStatus.STOPPING.value: "[yellow]",
        TaskStatus.LIVE_ENDED.value: "[green]",
        TaskStatus.FINALIZING.value: "[cyan]",
        TaskStatus.TRANSCRIBING.value: "[green]",
        TaskStatus.PROCESSING.value: "[green]",
        TaskStatus.SUMMARIZING.value: "[green]",
        TaskStatus.SAVING.value: "[green]",
        TaskStatus.IMPORTING_GETNOTE.value: "[green]",
        TaskStatus.COMPLETED.value: "[bold green]",
        TaskStatus.COMPLETED_WITH_MANUAL_STOP.value: "[bold yellow]",
        TaskStatus.FAILED.value: "[bold red]",
        TaskStatus.STOPPED.value: "[yellow]",
    }
    style = mapping.get(status, "")
    return f"{style}{status}[/]" if style else status


def version_callback(value: bool) -> None:
    if value:
        rprint(f"live2note {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        callback=version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
    config: Path | None = typer.Option(
        None, "--config", "-c", help="Path to config.yaml"
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """live2note — Live stream knowledge capture agent."""
    setup_logging(verbose=verbose)


# ── run helpers ─────────────────────────────────────────────


def _print_task_info(
    state, url, resolved_platform, segment, getnote, mgr, cfg, check_error, no_check
):

    lines = [f"[bold green]Task created:[/bold green] {state.task_id}"]
    lines.append(f"[bold]URL:[/bold]        {url}")
    lines.append(f"[bold]Platform:[/bold]   {resolved_platform}")
    lines.append(f"[bold]Source:[/bold]     {state.source_type}")

    if not no_check:
        live_str = "[green]LIVE[/green]" if not check_error else "[yellow]CHECK[/yellow]"
        lines.append(f"[bold]Live:[/bold]       {live_str}")
        if state.metadata.title:
            lines.append(f"[bold]Title:[/bold]      {state.metadata.title}")
        if state.metadata.streamer:
            lines.append(f"[bold]Streamer:[/bold]   {state.metadata.streamer}")
        if state.metadata.room_id:
            lines.append(f"[bold]Room ID:[/bold]    {state.metadata.room_id}")
        if state.metadata.stream_url:
            su = state.metadata.stream_url
            lines.append(f"[bold]Stream URL:[/bold] {su[:80]}{'...' if len(su) > 80 else ''}")

    lines.append(f"[bold]Duration:[/bold]   {state.duration or 'manual'} min")
    lines.append(f"[bold]Segment:[/bold]    {segment} min")
    lines.append(f"[bold]getnote:[/bold]    {'yes' if getnote else 'no'}")
    lines.append(f"[bold]Output:[/bold]     {mgr.base_dir / state.task_id}")
    lines.append("")
    lines.append(f"[dim]Config: {config_summary(cfg)}[/dim]")

    if check_error:
        lines.append(f"\n[red]Check: {check_error}[/red]")

    rprint(Panel("\n".join(lines), title="live2note run", border_style="blue"))


# ── monitor stop callback ───────────────────────────────────


def _handle_monitor_stop(mgr, state, task_dir, reason):
    """Called by LiveMonitor when stream goes offline."""
    from live2note.recorder.stop_controller import write_stop_flag

    write_stop_flag(task_dir, reason)
    state.request_stop(reason)
    mgr.save(state)


# ── run ─────────────────────────────────────────────────────


@app.command()
def run(
    url: str = typer.Argument(..., help="Live stream URL"),
    platform: str = typer.Option(
        "auto", help="Platform: auto | bilibili | douyin | generic"
    ),
    duration: int = typer.Option(
        0, "--duration", "-d", help="Recording duration in minutes (0 = manual stop)"
    ),
    segment: int = typer.Option(5, "--segment", "-s", help="Minutes per audio segment"),
    stream_url: str = typer.Option(
        "", "--stream-url", help="Direct stream URL override (skip adapter resolution)"
    ),
    getnote: bool = typer.Option(
        False, "--getnote", "-g", help="Export to getnote after processing"
    ),
    getnote_tag: list[str] = typer.Option(
        [], "--getnote-tag", help="Tags for getnote (repeatable)"
    ),
    no_check: bool = typer.Option(
        False, "--no-check", help="Skip live status check (use for offline testing)"
    ),
    no_record: bool = typer.Option(
        False, "--no-record", help="Skip recording (create task only)"
    ),
    config: Path | None = typer.Option(None, "--config", "-c", help="Config file path"),
) -> None:
    """Record a live stream, transcribe, and organize knowledge."""
    from live2note.adapters import get_adapter_or_raise, list_adapters

    cfg = load_config(config)
    mgr = _get_manager(cfg)

    # Resolve adapter.
    try:
        adapter = get_adapter_or_raise(url, platform)
    except ValueError as exc:
        rprint(f"[red]Error:[/red] {exc}")
        rprint(f"[dim]Available platforms: {', '.join(list_adapters())}[/dim]")
        raise typer.Exit(1) from None

    resolved_platform = adapter.get_platform()
    rprint(f"[dim]Adapter: {resolved_platform}[/dim]")

    # Create task.
    state = mgr.create(
        url=url,
        platform=platform,
        duration=duration,
        getnote=getnote,
        getnote_tags=getnote_tag,
    )

    # ── Step 1: check ──────────────────────────────────────
    check_error = None
    if not no_check:
        rprint("[dim]Checking live status...[/dim]")
        result = adapter.check_live(url)

        state.metadata.title = result.title
        state.metadata.streamer = result.streamer
        state.metadata.room_id = result.room_id
        state.metadata.platform = result.platform
        state.metadata.stream_url = result.stream_url
        state.source_type = result.platform
        state.finish_step("check")
        mgr.save(state)
        mgr.save_metadata(state)

        check_error = result.error
        if not stream_url and result.stream_url:
            stream_url = result.stream_url
    else:
        state.finish_step("check")
        mgr.save(state)

    # Print task info.
    _print_task_info(state, url, resolved_platform, segment, getnote, mgr, cfg, check_error, no_check)

    if no_record:
        rprint("[dim]Recording skipped (--no-record).[/dim]")
        return

    # ── Step 2: record ─────────────────────────────────────
    from live2note.recorder import FfmpegRecorder, StreamResolver

    # Resolve stream URL.
    try:
        resolver = StreamResolver()
        resolved_stream_url = resolver.resolve(state, adapter, stream_url)
    except ValueError as exc:
        rprint(f"[red]Stream URL error:[/red] {exc}")
        state.mark_failed(str(exc))
        mgr.save(state)
        raise typer.Exit(1) from None

    # Update metadata with resolved stream URL.
    state.metadata.stream_url = resolved_stream_url
    mgr.save_metadata(state)

    state.set_step("record")
    state.mark_started()
    mgr.save(state)

    rprint("\n[bold green]Recording started.[/bold green]  Ctrl+C to stop.")
    rprint(f"[dim]Stream: {resolved_stream_url[:80]}[/dim]")
    rprint(f"[dim]Segment: {segment} min | Duration: {duration or 'unlimited'} min[/dim]\n")

    import os

    recorder = FfmpegRecorder(
        ffmpeg_path=cfg.recording.ffmpeg_path,
        sample_rate=cfg.recording.audio_sample_rate,
        channels=cfg.recording.audio_channels,
    )

    task_dir = mgr.base_dir / state.task_id
    audio_dir = task_dir / "audio_segments"
    segment_seconds = segment * 60
    total_seconds = duration * 60 if duration > 0 else 0

    # Save our PID.
    state.pid = os.getpid()
    mgr.save(state)

    # Start live monitor (background thread).
    monitor = None
    if not no_check and resolved_platform != "generic":
        from live2note.recorder.live_monitor import LiveMonitor

        monitor = LiveMonitor(
            state=state,
            task_dir=task_dir,
            check_live_fn=adapter.check_live,
            stop_fn=lambda s, td, reason: _handle_monitor_stop(mgr, s, td, reason),
            save_fn=lambda s: mgr.save(s),
            interval_seconds=cfg.recording.live_check_interval_seconds,
            max_failures=cfg.recording.max_live_check_failures,
        )
        monitor.start()

    try:
        completed = recorder.record(
            stream_url=resolved_stream_url,
            output_dir=audio_dir,
            segment_seconds=segment_seconds,
            total_seconds=total_seconds,
            task_dir=task_dir,
            no_data_timeout=cfg.recording.no_data_timeout_seconds,
        )
    except FileNotFoundError:
        msg = f"ffmpeg not found at '{cfg.recording.ffmpeg_path}'. Install it and try again."
        rprint(f"[red]{msg}[/red]")
        state.mark_failed(msg)
        mgr.save(state)
        raise typer.Exit(1) from None
    finally:
        if monitor:
            monitor.stop()

    # Record ffmpeg PID for stop command.
    if recorder.last_ffmpeg_pid:
        state.ffmpeg_pid = recorder.last_ffmpeg_pid

    # Persist segments to task state.
    for i, seg in enumerate(completed, start=1):
        seg["index"] = i
        state.add_audio_segment(
            index=i,
            file=seg["file"],
            duration=float(seg["duration"]),
        )
        state.record_segment_time()
    mgr.save(state)

    # Determine how recording ended.
    from live2note.models.task import StopReason
    from live2note.recorder.stop_controller import read_stop_flag

    stop_flag = read_stop_flag(task_dir)

    if recorder.stop_requested or stop_flag:
        reason = (stop_flag or {}).get("reason", StopReason.MANUAL_STOP.value)
        state.mark_stopped(reason)
        rprint(f"\n[yellow]Recording stopped ({reason}).[/yellow]  {len(completed)} segment(s) saved.")
        mgr.save(state)
        rprint(f"[dim]Output: {audio_dir}[/dim]")
    elif len(completed) > 0:
        state.finish_step("record")
        # Check if live ended.
        if state.live_status == "ended":
            state.mark_stopped(StopReason.LIVE_ENDED.value)
            rprint(f"\n[green]Live stream ended.[/green]  {len(completed)} segment(s) recorded.")
        else:
            rprint(f"\n[green]Recording complete.[/green]  {len(completed)} segment(s) saved.")
    else:
        state.mark_failed("No segments recorded — stream may be offline.")
        rprint("\n[red]Recording failed — no segments captured.[/red]")
        mgr.save(state)
        return

    mgr.save(state)
    rprint(f"[dim]Output: {audio_dir}[/dim]")

    # ── Run remaining pipeline steps (also for stopped tasks) ─
    if len(completed) > 0:
        from live2note.pipeline import Pipeline

        stop_reason = state.stop_reason
        rprint("\n[bold]Finalizing...[/bold]")
        pipeline = Pipeline(mgr, cfg)
        state = pipeline.run(state, stop_reason=stop_reason)

        if state.status in ("COMPLETED", "COMPLETED_WITH_MANUAL_STOP"):
            rprint(f"\n[bold green]Done![/bold green]  Task: {state.task_id}  Status: {state.status}")
        elif state.status == "FAILED":
            rprint(f"\n[bold red]Pipeline failed.[/bold red]  {state.error_message}")
            rprint(f"[dim]Use 'live2note resume {state.task_id}' to retry.[/dim]")


# ── watch ───────────────────────────────────────────────────


@app.command()
def watch(
    url: str = typer.Argument(..., help="Live stream URL"),
    wait: bool = typer.Option(False, "--wait", "-w", help="Wait if stream is not live"),
    wait_timeout: int = typer.Option(60, "--wait-timeout", help="Max minutes to wait"),
    poll_interval: int = typer.Option(
        30, "--poll-interval", help="Poll interval in seconds"
    ),
    getnote: bool = typer.Option(False, "--getnote", "-g", help="Export to getnote"),
    getnote_tag: list[str] = typer.Option([], "--getnote-tag"),
    config: Path | None = typer.Option(None, "--config", "-c"),
) -> None:
    """Watch a live stream and start recording when it goes live."""
    rprint("[yellow][!] watch command is not yet implemented.[/yellow]")


# ── transcribe ──────────────────────────────────────────────


@app.command()
def transcribe(
    task_id: str = typer.Argument(..., help="Task ID to transcribe"),
    language: str = typer.Option("", "--lang", "-l", help="Override language (default from config)"),
    model_size: str = typer.Option("", "--model", "-m", help="Override model size"),
    config: Path | None = typer.Option(None, "--config", "-c"),
) -> None:
    """Transcribe all audio segments of a task."""
    cfg = load_config(config)
    mgr = _get_manager(cfg)

    if not mgr.task_exists(task_id):
        rprint(f"[red]Task not found: {task_id}[/red]")
        raise typer.Exit(1)

    state = mgr.load(task_id)

    if not state.audio_segments:
        rprint("[yellow]No audio segments to transcribe.[/yellow]")
        raise typer.Exit(1)

    from live2note.transcriber import (
        WhisperEngine,
        write_transcript_json,
        write_transcript_markdown,
    )

    engine = WhisperEngine(
        model_size=model_size or cfg.transcription.model_size,
        language=language or cfg.transcription.language,
        device=cfg.transcription.device,
        compute_type=cfg.transcription.compute_type,
        beam_size=cfg.transcription.beam_size,
        vad_filter=cfg.transcription.vad_filter,
    )

    task_dir = mgr.base_dir / task_id
    transcripts_dir = task_dir / "transcripts"

    state.set_step("transcribe")
    mgr.save(state)

    global_offset = 0.0
    completed = 0
    skipped = 0
    failed = 0

    for seg_info in state.audio_segments:
        idx = seg_info["index"]
        audio_file = seg_info["file"]
        seg_duration = float(seg_info.get("duration", 0))

        # Resolve path relative to task dir if needed.
        audio_path = Path(audio_file)
        if not audio_path.is_absolute():
            audio_path = task_dir / audio_path

        if state.has_transcript(idx):
            skipped += 1
            global_offset += seg_duration
            rprint(f"[dim]  Segment {idx:03d}: already transcribed, skipping[/dim]")
            continue

        if not audio_path.is_file():
            rprint(f"[yellow]  Segment {idx:03d}: file not found — {audio_path.name}[/yellow]")
            failed += 1
            global_offset += seg_duration
            continue

        rprint(f"  Segment {idx:03d}: transcribing {audio_path.name}...")

        try:
            segments = engine.transcribe(audio_path)
        except Exception as exc:
            rprint(f"[red]  Segment {idx:03d}: failed — {exc}[/red]")
            failed += 1
            global_offset += seg_duration
            continue

        stem = f"segment_{idx:03d}"
        json_path = transcripts_dir / f"{stem}.json"
        md_path = transcripts_dir / f"{stem}.md"

        write_transcript_json(
            json_path, idx, audio_path.name, segments, global_offset
        )
        write_transcript_markdown(
            md_path, idx, audio_path.name, segments, global_offset
        )

        state.add_transcript(idx, str(json_path))
        mgr.save(state)

        completed += 1
        global_offset += seg_duration

    if completed > 0 and failed == 0:
        state.finish_step("transcribe")
        rprint(f"\n[green]Transcription complete.[/green]  {completed} done, {skipped} skipped.")
    elif completed > 0:
        rprint(f"\n[yellow]Transcription partial.[/yellow]  {completed} done, {skipped} skipped, {failed} failed.")
    elif skipped > 0 and failed == 0:
        state.finish_step("transcribe")
        rprint(f"\n[green]All {skipped} segments already transcribed.[/green]")
    else:
        state.mark_failed(f"Transcription failed: {failed} segment(s).")
        rprint(f"\n[red]Transcription failed.[/red]  {failed} failed, {skipped} skipped.")

    mgr.save(state)
    rprint(f"[dim]Transcripts: {transcripts_dir}[/dim]")


# ── process ─────────────────────────────────────────────────


@app.command()
def process(
    task_id: str = typer.Argument(..., help="Task ID to process"),
    skip_llm: bool = typer.Option(
        False, "--skip-llm", help="Skip LLM summarization (chunking only)"
    ),
    min_chars: int = typer.Option(800, "--min-chars", help="Min characters per chunk"),
    max_chars: int = typer.Option(1500, "--max-chars", help="Max characters per chunk"),
    provider_override: str = typer.Option(
        "", "--provider", help="Override LLM provider: auto | openai_compatible | anthropic | external_cli | prompt_only"
    ),
    config: Path | None = typer.Option(None, "--config", "-c"),
) -> None:
    """Clean transcripts, chunk them, and summarize with LLM."""
    import json as _json

    cfg = load_config(config)
    mgr = _get_manager(cfg)

    if not mgr.task_exists(task_id):
        rprint(f"[red]Task not found: {task_id}[/red]")
        raise typer.Exit(1)

    state = mgr.load(task_id)
    task_dir = mgr.base_dir / task_id
    transcripts_dir = task_dir / "transcripts"

    # ── Load transcripts ──────────────────────────────────
    from live2note.processor.chunker import chunk_segments
    from live2note.processor.cleaner import CleanSegment, clean_segments

    transcript_files = sorted(transcripts_dir.glob("segment_*.json"))
    if not transcript_files:
        rprint("[yellow]No transcript files found. Run 'transcribe' first.[/yellow]")
        raise typer.Exit(1)

    all_segments: list[CleanSegment] = []
    for tf in transcript_files:
        data = _json.loads(tf.read_text(encoding="utf-8"))
        for seg in data.get("segments", []):
            all_segments.append(
                CleanSegment(
                    start=seg["global_start"],
                    end=seg["global_end"],
                    text=seg["text"],
                )
            )

    rprint(f"[dim]Loaded {len(all_segments)} segments from {len(transcript_files)} file(s).[/dim]")

    # ── Clean ─────────────────────────────────────────────
    cleaned = clean_segments(all_segments)
    rprint(f"[dim]After cleaning: {len(cleaned)} segments.[/dim]")

    # ── Chunk ─────────────────────────────────────────────
    chunks = chunk_segments(cleaned, min_chars=min_chars, max_chars=max_chars)
    rprint(f"[dim]Split into {len(chunks)} chunk(s).[/dim]")

    if not chunks:
        rprint("[yellow]No content to process — transcripts may be empty.[/yellow]")
        state.finish_step("process")
        mgr.save(state)
        return

    # Save chunks.
    chunks_dir = task_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    chunks_path = chunks_dir / "chunks.json"
    chunks_data = [
        {
            "chunk_id": c.chunk_id,
            "start": c.start,
            "end": c.end,
            "text": c.text,
            "source_segments": c.source_segments,
        }
        for c in chunks
    ]
    chunks_path.write_text(
        _json.dumps(chunks_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    state.finish_step("process")
    mgr.save(state)
    rprint(f"[green]Chunks saved:[/green] {chunks_path}")

    # ── Summarize ─────────────────────────────────────────
    if skip_llm:
        rprint("[dim]LLM summarization skipped (--skip-llm).[/dim]")
        return

    from live2note.llm import create_provider
    from live2note.processor.summarizer import Summarizer

    prompts_dir = task_dir / "prompts"
    provider = create_provider(cfg.llm, output_dir=prompts_dir, provider_override=provider_override or "")
    summarizer = Summarizer(provider=provider)

    if not summarizer.is_configured:
        rprint(
            "[yellow]LLM API key not configured.[/yellow]\n"
            "[dim]Set llm.api_key in config.yaml or export LLM_API_KEY.\n"
            "Use --skip-llm to save chunks without summarization.\n"
            "Use 'live2note llm doctor' to check your LLM setup.[/dim]"
        )
        return

    if summarizer.provider_name == "prompt_only":
        rprint(
            "[yellow]No API key found — using prompt_only mode.[/yellow]\n"
            f"[dim]Prompts saved to: {prompts_dir}[/dim]"
        )

    summaries_dir = task_dir / "summaries"
    summaries_dir.mkdir(parents=True, exist_ok=True)

    state.set_step("summarize")
    mgr.save(state)

    summaries = []
    for chunk in chunks:
        rprint(f"  Summarizing chunk {chunk.chunk_id}/{len(chunks)}...")
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
            rprint(f"[red]  Chunk {chunk.chunk_id} failed: {exc}[/red]")
            summaries.append({
                "chunk_id": chunk.chunk_id,
                "start": chunk.start,
                "end": chunk.end,
                "summary": f"[Error: {exc}]",
                "key_points": [],
                "knowledge_points": [],
                "action_items": [],
                "tags": [],
                "keywords": [],
                "important_quotes": [],
            })

    summaries_path = summaries_dir / "chunk_summaries.json"
    summaries_path.write_text(
        _json.dumps(summaries, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    state.finish_step("summarize")
    mgr.save(state)
    rprint(f"[green]Summaries saved:[/green] {summaries_path}")
    rprint(f"[dim]Processed {len(summaries)} chunk(s).[/dim]")

    # Auto-generate final note after summarization.
    _generate_final_note(mgr, state, task_dir, cfg)


# ── save (generate final note) ──────────────────────────────


@app.command()
def save(
    task_id: str = typer.Argument(..., help="Task ID to generate final note for"),
    config: Path | None = typer.Option(None, "--config", "-c"),
) -> None:
    """Generate final_note.md and final_note.json from chunks and summaries."""
    cfg = load_config(config)
    mgr = _get_manager(cfg)

    if not mgr.task_exists(task_id):
        rprint(f"[red]Task not found: {task_id}[/red]")
        raise typer.Exit(1)

    state = mgr.load(task_id)
    task_dir = mgr.base_dir / task_id
    _generate_final_note(mgr, state, task_dir, cfg)


def _generate_final_note(mgr, state, task_dir, cfg):
    """Shared logic for building the final note."""
    import json as _json

    from live2note.processor.final_note_builder import build_final_note
    from live2note.storage import write_final_json, write_final_markdown

    # Load chunks.
    chunks_path = task_dir / "chunks" / "chunks.json"
    if not chunks_path.is_file():
        rprint("[yellow]No chunks found. Run 'process' first.[/yellow]")
        return

    chunks = _json.loads(chunks_path.read_text(encoding="utf-8"))

    # Load summaries (optional).
    summaries_path = task_dir / "summaries" / "chunk_summaries.json"
    summaries = None
    if summaries_path.is_file():
        summaries = _json.loads(summaries_path.read_text(encoding="utf-8"))

    # Build note.
    note = build_final_note(
        task_id=state.task_id,
        metadata=state.metadata.to_dict(),
        chunks=chunks,
        summaries=summaries,
    )

    # Write outputs.
    notes_dir = task_dir / "notes"
    md_path = notes_dir / "final_note.md"
    json_path = notes_dir / "final_note.json"

    write_final_markdown(note, md_path)
    write_final_json(note, json_path)

    # Update task state.
    state.final_note_path = str(md_path)
    state.finish_step("save")
    mgr.save(state)

    rprint("[green]Final note generated:[/green]")
    rprint(f"  Markdown: {md_path}")
    rprint(f"  JSON:     {json_path}")

    # Auto-import to getnote if enabled (global config or per-task flag).
    if cfg.getnote.enabled or state.getnote_enabled:
        rprint("")
        _run_getnote_import(mgr, state, cfg)


def _run_getnote_import(mgr, state, cfg, force: bool = False) -> None:
    """Import final_note.md into getnote. Non-blocking on failure."""
    from datetime import datetime, timezone

    from live2note.storage.getnote import import_to_getnote

    if state.getnote_imported and not force:
        rprint("[dim]Already imported to getnote.[/dim]")
        return

    if not state.final_note_path:
        rprint("[yellow]No final note to import. Run 'save' first.[/yellow]")
        return

    md_path = Path(state.final_note_path)
    if not md_path.is_file():
        rprint(f"[yellow]Final note not found: {md_path}. Run 'save' first.[/yellow]")
        return

    gn = cfg.getnote
    title = state.metadata.title or state.task_id
    tags = list(gn.default_tags) + list(state.getnote_tags)

    rprint(f"[dim]Importing to getnote: {md_path.name}...[/dim]")

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
        rprint("[green]getnote import succeeded.[/green]")
        if result.stdout:
            safe_out = result.stdout[:200].encode("ascii", "replace").decode("ascii")
            rprint(f"[dim]{safe_out}[/dim]")
    else:
        state.getnote_imported = False
        state.getnote_error = result.message
        rprint(f"[yellow]getnote import failed: {result.message}[/yellow]")
        rprint("[dim]Local files are unaffected.[/dim]")

    mgr.save(state)


# ── import-getnote ──────────────────────────────────────────


@app.command(name="import-getnote")
def import_getnote(
    task_id: str = typer.Argument(..., help="Task ID to import"),
    force: bool = typer.Option(False, "--force", "-f", help="Re-import even if already done"),
    config: Path | None = typer.Option(None, "--config", "-c"),
) -> None:
    """Import the task's final note into getnote."""
    cfg = load_config(config)
    mgr = _get_manager(cfg)

    if not mgr.task_exists(task_id):
        rprint(f"[red]Task not found: {task_id}[/red]")
        raise typer.Exit(1)

    state = mgr.load(task_id)
    _run_getnote_import(mgr, state, cfg, force=force)


# ── stop ────────────────────────────────────────────────────


@app.command()
def stop(
    task_id: str = typer.Argument(..., help="Task ID to stop"),
    force: bool = typer.Option(False, "--force", help="Force kill ffmpeg immediately"),
    config: Path | None = typer.Option(None, "--config", "-c"),
) -> None:
    """Stop a running recording task."""

    from live2note.models.task import StopReason
    from live2note.recorder.stop_controller import (
        request_stop,
        stop_ffmpeg,
        write_stop_flag,
    )

    cfg = load_config(config)
    mgr = _get_manager(cfg)

    if not mgr.task_exists(task_id):
        rprint(f"[red]Task not found: {task_id}[/red]")
        raise typer.Exit(1)

    state = mgr.load(task_id)
    task_dir = mgr.base_dir / task_id

    if state.status not in (
        TaskStatus.RECORDING.value,
        TaskStatus.STOP_REQUESTED.value,
        TaskStatus.CHECKING.value,
    ):
        rprint(f"[yellow]Task is not recording (status={state.status}).[/yellow]")
        rprint("[dim]Stop only applies to active recording tasks.[/dim]")
        raise typer.Exit(1)

    # Write stop flag and update state.
    write_stop_flag(task_dir, StopReason.MANUAL_STOP.value)
    request_stop(state, task_dir, StopReason.MANUAL_STOP.value)
    mgr.save(state)

    rprint(f"[yellow]Stop requested for task {task_id}[/yellow]")

    # Try to stop ffmpeg.
    if state.ffmpeg_pid:
        grace = 0 if force else cfg.recording.stop_grace_seconds
        stopped = stop_ffmpeg(state, grace_seconds=grace)
        if stopped:
            rprint("[green]ffmpeg stopped.[/green]")
        else:
            rprint("[red]ffmpeg could not be stopped. Try --force.[/red]")
    else:
        rprint("[dim]No ffmpeg PID recorded. Stop flag written for the recording loop.[/dim]")

    rprint(f"[dim]Use 'live2note resume {task_id}' to finalize remaining content.[/dim]")


# ── resume ──────────────────────────────────────────────────


@app.command()
def resume(
    task_id: str = typer.Argument(..., help="Task ID to resume"),
    config: Path | None = typer.Option(None, "--config", "-c"),
) -> None:
    """Resume a previously interrupted task."""
    cfg = load_config(config)
    mgr = _get_manager(cfg)

    if not mgr.task_exists(task_id):
        rprint(f"[red]Task not found: {task_id}[/red]")
        raise typer.Exit(1)

    state = mgr.resume(task_id)

    if state.status == TaskStatus.COMPLETED.value:
        rprint(f"[green]Task {task_id} is already completed.[/green]")
        return

    from live2note.models.task import PIPELINE_STEPS

    next_step = state.next_step()
    remaining = [s for s in PIPELINE_STEPS if not state.is_step_done(s)]

    rprint(
        Panel(
            f"[bold green]Resuming:[/bold green] {task_id}\n"
            f"[bold]Retry:[/bold]     {state.retry_count}\n"
            f"[bold]Next step:[/bold] {next_step or '(none)'}\n"
            f"[bold]Done:[/bold]      {', '.join(state.finished_steps) or '(none)'}\n"
            f"[bold]Remaining:[/bold] {', '.join(remaining)}",
            title="live2note resume",
            border_style="blue",
        )
    )

    # Run pipeline from current position.
    from live2note.pipeline import Pipeline

    pipeline = Pipeline(mgr, cfg)
    state = pipeline.run(state, stop_reason=state.stop_reason)

    if state.status in ("COMPLETED", "COMPLETED_WITH_MANUAL_STOP"):
        rprint(f"\n[bold green]Pipeline complete![/bold green]  Task: {state.task_id}")
    elif state.status == "FAILED":
        rprint(f"\n[bold red]Pipeline failed.[/bold red]  {state.error_message}")
        rprint(f"[dim]Use 'live2note resume {state.task_id}' to retry.[/dim]")


# ── status ──────────────────────────────────────────────────


@app.command()
def status(
    task_id: str | None = typer.Argument(
        None, help="Task ID (blank = most recent)"
    ),
    config: Path | None = typer.Option(None, "--config", "-c"),
) -> None:
    """Show task status."""
    cfg = load_config(config)
    mgr = _get_manager(cfg)

    if task_id:
        if not mgr.task_exists(task_id):
            rprint(f"[red]Task not found: {task_id}[/red]")
            raise typer.Exit(1)
        state = mgr.load(task_id)
    else:
        state = mgr.get_latest()
        if state is None:
            rprint("[yellow]No tasks found.[/yellow]")
            raise typer.Exit()

    from live2note.models.task import PIPELINE_STEPS

    table = Table(title=f"Task: {state.task_id}", show_lines=True)
    table.add_column("Field", style="bold")
    table.add_column("Value")

    table.add_row("Status", _status_style(state.status))
    table.add_row("URL", state.url)
    table.add_row("Platform", state.platform)
    table.add_row("Source type", state.source_type or "-")
    table.add_row("Duration", f"{state.duration} min" if state.duration else "manual")
    table.add_row("Created", state.created_at)
    table.add_row("Updated", state.updated_at)
    table.add_row("Started", state.started_at or "-")
    table.add_row("Ended", state.ended_at or "-")
    table.add_row("Current step", state.current_step or "-")
    table.add_row("Retry count", str(state.retry_count))

    if state.metadata.streamer:
        table.add_row("Streamer", state.metadata.streamer)
    if state.metadata.title:
        table.add_row("Title", state.metadata.title)
    if state.error_message:
        table.add_row("Error", f"[red]{state.error_message}[/red]")

    table.add_row("Segments", str(len(state.audio_segments)))
    table.add_row("Transcripts", str(len(state.transcripts)))
    table.add_row("Summaries", str(len(state.summaries)))
    table.add_row("Note path", state.final_note_path or "-")
    table.add_row("getnote", "imported" if state.getnote_imported else "no")
    table.add_row("ffmpeg PID", str(state.ffmpeg_pid) if state.ffmpeg_pid else "-")
    table.add_row("Live status", state.live_status)
    table.add_row("Stop requested", str(state.stop_requested))
    if state.stop_reason:
        table.add_row("Stop reason", state.stop_reason)

    # Pipeline progress
    table.add_row("--- Pipeline ---", "---")
    for step in PIPELINE_STEPS:
        if state.is_step_done(step):
            table.add_row(f"  {step}", "[green]done[/green]")
        elif state.current_step == step:
            table.add_row(f"  {step}", "[yellow]running[/yellow]")
        else:
            table.add_row(f"  {step}", "[dim]pending[/dim]")

    table.add_row("Finished", ", ".join(state.finished_steps) or "(none)")

    console.print(table)


# ── list ────────────────────────────────────────────────────


@app.command(name="list")
def list_tasks(
    status_filter: str | None = typer.Option(
        None, "--status", "-s", help="Filter by status, e.g. CREATED | FAILED"
    ),
    limit: int = typer.Option(20, "--limit", "-n"),
    config: Path | None = typer.Option(None, "--config", "-c"),
) -> None:
    """List all tasks."""
    cfg = load_config(config)
    mgr = _get_manager(cfg)
    tasks = mgr.list_tasks(status_filter=status_filter, limit=limit)

    if not tasks:
        rprint("[yellow]No tasks found.[/yellow]")
        return

    table = Table(title="Tasks", show_lines=True)
    table.add_column("Task ID", style="bold")
    table.add_column("Status")
    table.add_column("Source")
    table.add_column("URL")
    table.add_column("Steps done")
    table.add_column("Created")

    for t in tasks:
        done = f"{len(t.finished_steps)}/7"
        table.add_row(
            t.task_id,
            _status_style(t.status),
            t.source_type or t.platform,
            t.url[:40] + ("..." if len(t.url) > 40 else ""),
            done,
            t.created_at[:19],
        )

    console.print(table)


# ── config init ─────────────────────────────────────────────


@app.command(name="config-init")
def config_init(
    path: Path | None = typer.Argument(
        None, help="Output path (default: ~/.live2note/config.yaml)"
    ),
) -> None:
    """Generate default configuration file."""
    target = init_config(path)
    rprint(f"[green]Config written to:[/green] {target}")


# ── llm doctor ─────────────────────────────────────────────



@app.command(name="llm-doctor")
def llm_doctor(
    config: Path | None = typer.Option(None, "--config", "-c"),
) -> None:
    """Check LLM configuration and availability."""
    cfg = load_config(config)
    from live2note.llm import create_provider, detect_env, detect_external_cli, mask_key

    rprint("[bold]LLM Configuration Check[/bold]\n")
    rprint(f"  Config provider:     {cfg.llm.provider}")
    rprint(f"  Config model:        {cfg.llm.model}")
    rprint(f"  Config base URL:     {cfg.llm.api_base}")

    env = detect_env()
    if env.api_key:
        rprint(f"  Env API key:         {mask_key(env.api_key)}")
    else:
        rprint("  Env API key:         [yellow]not detected[/yellow]")
    rprint(f"  Detected provider:   {env.provider or 'none'}")

    # External CLI check.
    ec = cfg.llm.external_cli if hasattr(cfg.llm, "external_cli") else {}
    ec_enabled = ec.get("enabled") if ec else False
    ec_command = ec.get("command", "") if ec else ""
    rprint(f"  External CLI config: {'[green]enabled[/green]' if ec_enabled else '[dim]disabled[/dim]'}")
    if ec_command:
        rprint(f"    Command:           {ec_command}")

    auto_cmd = detect_external_cli()
    if auto_cmd:
        rprint(f"  Auto-detect CLI:     [green]{auto_cmd}[/green]")
    else:
        rprint("  Auto-detect CLI:     [yellow]none found in PATH[/yellow]")

    provider = create_provider(cfg.llm)
    rprint(f"\n  Active provider:     {provider.name}")
    rprint(f"  Available:           {'[green]yes[/green]' if provider.is_available else '[red]no[/red]'}")

    rprint("\n[dim]Tip: Set OPENAI_API_KEY, ANTHROPIC_API_KEY, or configure llm.external_cli[/dim]")
    rprint("[dim]Try: live2note llm-test --provider external_cli --prompt '你好'[/dim]")


# ── llm test ────────────────────────────────────────────────


@app.command(name="llm-test")
def llm_test(
    prompt: str = typer.Option("用一句话介绍你自己。", "--prompt", "-p", help="Test prompt"),
    provider_override: str = typer.Option(
        "", "--provider", help="Override LLM provider: auto | openai_compatible | anthropic | external_cli | prompt_only"
    ),
    config: Path | None = typer.Option(None, "--config", "-c"),
) -> None:
    """Send a test prompt to the configured LLM."""
    cfg = load_config(config)
    from live2note.llm import create_provider

    provider = create_provider(cfg.llm, provider_override=provider_override or "")

    if not provider.is_available:
        rprint("[red]No LLM provider available.[/red]")
        rprint("Run 'live2note llm-doctor' for details.")
        raise typer.Exit(1)

    rprint(f"[dim]Calling provider: {provider.name}[/dim]")
    rprint(f"[dim]Prompt: {prompt}[/dim]\n")

    result = provider.generate(prompt)

    if result.error and not result.text:
        rprint(f"[red]Error: {result.error}[/red]")
        raise typer.Exit(1)

    rprint(f"[green]Response:[/green]\n{result.text[:1000]}")


# ── export-prompts ──────────────────────────────────────────


@app.command(name="export-prompts")
def export_prompts(
    task_id: str = typer.Argument(..., help="Task ID"),
    config: Path | None = typer.Option(None, "--config", "-c"),
) -> None:
    """Export LLM summary prompts for a task without calling any API."""
    import json as _json

    cfg = load_config(config)
    mgr = _get_manager(cfg)

    if not mgr.task_exists(task_id):
        rprint(f"[red]Task not found: {task_id}[/red]")
        raise typer.Exit(1)

    task_dir = mgr.base_dir / task_id
    chunks_path = task_dir / "chunks" / "chunks.json"
    if not chunks_path.is_file():
        rprint("[yellow]No chunks found. Run 'process' first.[/yellow]")
        raise typer.Exit(1)

    chunks = _json.loads(chunks_path.read_text(encoding="utf-8"))
    prompts_dir = task_dir / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)

    from live2note.prompts import CHUNK_PROMPT_TEMPLATE, SYSTEM_PROMPT

    for chunk in chunks:
        cid = chunk["chunk_id"]
        text = chunk.get("text", "")
        prompt = f"{SYSTEM_PROMPT}\n\n{CHUNK_PROMPT_TEMPLATE.format(text=text)}"
        filepath = prompts_dir / f"chunk_{cid:03d}_prompt.md"
        filepath.write_text(prompt, encoding="utf-8")

    rprint(f"[green]Exported {len(chunks)} prompt(s) to: {prompts_dir}[/green]")
    rprint("[dim]Copy these prompts to any LLM or agent for processing.[/dim]")
    rprint("[dim]Then use 'live2note import-summary' to import results.[/dim]")
