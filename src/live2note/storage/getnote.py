"""getnote CLI integration — import notes via subprocess."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from live2note.logger import get_logger

log = get_logger("storage.getnote")


@dataclass(frozen=True)
class GetnoteResult:
    success: bool
    message: str
    stdout: str = ""
    stderr: str = ""


def import_to_getnote(
    file_path: Path | str,
    command_template: str = 'getnote save "{file_path}" --title "{title}"',
    title: str = "",
    tags: list[str] | None = None,
    timeout: int = 60,
) -> GetnoteResult:
    """Execute the getnote CLI command to import a note.

    Args:
        file_path: Path to the Markdown file to import.
        command_template: Shell command template with {file_path} and {title} placeholders.
        title: Note title (substituted into template).
        tags: Optional tags (appended as --tag flags).
        timeout: Subprocess timeout in seconds.

    Returns:
        GetnoteResult with success status and output.
    """
    file_path = Path(file_path)
    if not file_path.is_file():
        return GetnoteResult(
            success=False,
            message=f"File not found: {file_path}",
        )

    # Build command from template.
    cmd_str = command_template.format(
        file_path=str(file_path),
        title=title or file_path.stem,
    )

    # Append tags.
    if tags:
        for tag in tags:
            cmd_str += f' --tag "{tag}"'

    log.info("Running: %s", cmd_str)

    try:
        result = subprocess.run(
            cmd_str,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        msg = f"getnote command timed out after {timeout}s"
        log.error(msg)
        return GetnoteResult(success=False, message=msg)
    except FileNotFoundError:
        msg = "getnote command not found. Install it: go install github.com/nicepkg/getnote@latest"
        log.error(msg)
        return GetnoteResult(success=False, message=msg)

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()

    if result.returncode == 0:
        log.info("getnote import succeeded: %s", stdout[:200])
        return GetnoteResult(
            success=True,
            message="Imported successfully",
            stdout=stdout,
            stderr=stderr,
        )
    else:
        msg = f"getnote exited with code {result.returncode}"
        log.warning("getnote failed: %s | stderr: %s", msg, stderr[:200])
        return GetnoteResult(
            success=False,
            message=msg,
            stdout=stdout,
            stderr=stderr,
        )
