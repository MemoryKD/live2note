"""External CLI provider — calls a user-configured command via subprocess.

The prompt is passed via stdin. The command's stdout is captured as the LLM response.
No API keys are stored or read by this provider.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from live2note.llm.base import BaseLLMProvider, LLMResult
from live2note.logger import get_logger

log = get_logger("llm.external_cli")

_TOKEN_PATTERN = re.compile(r"(sk-[a-zA-Z0-9\-]{8,}|ant-[a-zA-Z0-9\-]{8,})")


def _redact_sensitive(text: str) -> str:
    """Mask potential API keys in text for safe logging.

    Shows first 4 and last 4 characters of the token.
    """
    def _mask(match):
        token = match.group(0)
        if len(token) <= 8:
            return "****"
        return token[:4] + "****" + token[-4:]
    return _TOKEN_PATTERN.sub(_mask, text)


def _resolve_command(command: str, args: list[str] | None = None) -> tuple[str | None, list[str] | None, str | None]:
    """Resolve a command string + optional args to executable path and full arg list.

    Returns (executable_path, full_args, error_message).
    On Windows, also tries .cmd and .exe suffixes.

    Backward compat: if command contains spaces and args is empty, split command.
    e.g. "claude -p" → command="claude", args=["-p"]
    """
    if not command.strip():
        return None, None, "Command is empty"

    args = args or []
    cmd = command.strip()

    # Backward compat: "claude -p" style combined command.
    if " " in cmd and not args:
        parts = cmd.split()
        cmd = parts[0]
        args = parts[1:]

    exe_name = cmd

    # Try shutil.which first (searches PATH).
    resolved = shutil.which(exe_name)
    if not resolved and os.name == "nt":
        for ext in (".cmd", ".exe", ".bat", ".ps1"):
            resolved = shutil.which(exe_name + ext)
            if resolved:
                break

    if not resolved:
        return None, None, f"Command not found in PATH: {exe_name}"

    full_args = [resolved] + (args or [])
    return resolved, full_args, None


class ExternalCLIProvider(BaseLLMProvider):
    """Runs an external CLI command, passes prompt via stdin, captures stdout.

    Configuration example:
      command: "claude"
      args: ["-p"]
      timeout_seconds: 600
      fallback_to_prompt_only: true

    The command is resolved via shutil.which() for cross-platform support.
    live2note does NOT read the external tool's internal auth files.
    """

    def __init__(
        self,
        command: str = "",
        args: list[str] | None = None,
        timeout_seconds: int = 600,
        input_mode: str = "stdin",
        working_dir: str = "",
        fallback_to_prompt_only: bool = True,
    ) -> None:
        self._command = command
        self._args = args or []
        self._timeout = timeout_seconds
        self._input_mode = input_mode
        self._working_dir = working_dir
        self._fallback_to_prompt_only = fallback_to_prompt_only

    @property
    def is_available(self) -> bool:
        if not self._command:
            return False
        resolved, _, _ = _resolve_command(self._command, self._args)
        return resolved is not None

    @property
    def name(self) -> str:
        args_str = " ".join(self._args) if self._args else ""
        return f"external_cli({self._command} {args_str})".strip()

    @property
    def fallback_to_prompt_only(self) -> bool:
        return self._fallback_to_prompt_only

    def generate(self, prompt: str, **kwargs: Any) -> LLMResult:
        if not self._command:
            return LLMResult(text="", error="External CLI command not configured")

        resolved, full_args, err = _resolve_command(self._command, self._args)
        if err:
            log.error("External CLI: %s", err)
            return LLMResult(text="", error=err)

        working_dir = Path(self._working_dir) if self._working_dir else None

        if self._input_mode != "stdin":
            return LLMResult(
                text="",
                error=f"Unsupported input_mode: {self._input_mode}",
            )

        log.info("Running external CLI (stdin mode): %s", resolved)
        # Log args but not full prompt for security.
        log.debug("External CLI args: %s", full_args)
        log.debug("External CLI prompt length: %d chars", len(prompt))

        try:
            proc = subprocess.run(
                full_args,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                encoding="utf-8",
                errors="replace",
                cwd=working_dir,
            )
        except FileNotFoundError:
            msg = f"Command not found: {resolved}"
            log.error(msg)
            return LLMResult(text="", error=msg)
        except subprocess.TimeoutExpired:
            msg = f"External CLI timed out after {self._timeout}s"
            log.error(msg)
            return LLMResult(text="", error=msg)
        except OSError as exc:
            log.error("External CLI error: %s", exc)
            return LLMResult(text="", error=str(exc))

        stdout = proc.stdout.strip()
        stderr = _redact_sensitive(proc.stderr.strip() if proc.stderr else "")

        if proc.returncode != 0:
            log.warning(
                "External CLI exited code=%d: %s",
                proc.returncode,
                stderr[:200] if stderr else "(no stderr)",
            )
            if not stdout:
                return LLMResult(
                    text="",
                    error=f"CLI exited code {proc.returncode}: {stderr[:200]}",
                )
            # Non-zero but has stdout — still use it.

        if stderr:
            log.debug("External CLI stderr: %s", stderr[:200])

        return LLMResult(text=stdout, metadata={"returncode": proc.returncode})


# Agents to auto-detect in PATH, in priority order.
_AUTO_DETECT_CANDIDATES = [
    "claude",
    "codex",
    "opencode",
    "openclaw",
    "hermes",
    "cg",
]


def detect_external_cli() -> str | None:
    """Auto-detect an available external CLI command in PATH.

    Checks for: claude, codex, opencode, openclaw, hermes, cg
    Returns the first found command string, or None.
    """
    for name in _AUTO_DETECT_CANDIDATES:
        resolved = shutil.which(name)
        if resolved:
            log.info("Auto-detected external CLI: %s", resolved)
            return resolved
        if os.name == "nt":
            for ext in (".cmd", ".exe", ".bat"):
                resolved = shutil.which(name + ext)
                if resolved:
                    log.info("Auto-detected external CLI: %s", resolved)
                    return resolved
    return None
