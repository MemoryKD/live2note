"""Tests for LLM provider system."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from live2note.llm.base import BaseLLMProvider, LLMResult
from live2note.llm.external_cli import (
    ExternalCLIProvider,
    _redact_sensitive,
    _resolve_command,
    detect_external_cli,
)
from live2note.llm.provider_registry import create_provider
from live2note.llm.env_detector import detect_env, mask_key


# ── _redact_sensitive ──────────────────────────────────────────

def test_redact_openai_key():
    result = _redact_sensitive("sk-proj-1234567890abcdef")
    assert "****" in result
    assert result.startswith("sk-p")
    assert result.endswith("cdef")

def test_redact_anthropic_key():
    result = _redact_sensitive("ant-api-abcdefghijklmnop")
    assert "****" in result
    assert result.startswith("ant-")
    assert result.endswith("mnop")

def test_redact_no_key():
    assert _redact_sensitive("normal text") == "normal text"


# ── mask_key ───────────────────────────────────────────────────

def test_mask_key_normal():
    result = mask_key("sk-ant-api-1234567890abcdefgh")
    assert result.startswith("sk-a")
    assert result.endswith("fgh")
    assert "****" in result

def test_mask_key_short():
    assert mask_key("short") == "****"

def test_mask_key_empty():
    assert mask_key("") == "****"


# ── _resolve_command ───────────────────────────────────────────

def test_resolve_command_empty():
    resolved, full_args, err = _resolve_command("")
    assert resolved is None
    assert err is not None

def test_resolve_command_whitespace():
    resolved, full_args, err = _resolve_command("   ")
    assert resolved is None

def test_resolve_command_found():
    with patch("live2note.llm.external_cli.shutil.which", return_value="/usr/bin/python"):
        resolved, full_args, err = _resolve_command("python")
        assert resolved == "/usr/bin/python"
        assert err is None
        assert full_args == ["/usr/bin/python"]

def test_resolve_command_with_args():
    with patch("live2note.llm.external_cli.shutil.which", return_value="/usr/bin/python"):
        resolved, full_args, err = _resolve_command("python", args=["-c", "print(1)"])
        assert resolved == "/usr/bin/python"
        assert err is None
        assert full_args == ["/usr/bin/python", "-c", "print(1)"]

def test_resolve_command_not_found():
    with patch("live2note.llm.external_cli.shutil.which", return_value=None):
        resolved, full_args, err = _resolve_command("nonexistent_cmd_xyz")
        assert resolved is None
        assert "not found" in err

def test_resolve_command_windows_extensions():
    with (
        patch("live2note.llm.external_cli.os.name", "nt"),
        patch("live2note.llm.external_cli.shutil.which") as mock_which,
    ):
        mock_which.side_effect = lambda x: (
            "C:\\bin\\claude.cmd" if x == "claude.cmd" else None
        )
        resolved, full_args, err = _resolve_command("claude")
        assert resolved == "C:\\bin\\claude.cmd"
        assert err is None


# ── ExternalCLIProvider ────────────────────────────────────────

def test_external_cli_not_available_empty_command():
    provider = ExternalCLIProvider(command="")
    assert not provider.is_available

def test_external_cli_not_available_bad_command():
    with patch("live2note.llm.external_cli.shutil.which", return_value=None):
        provider = ExternalCLIProvider(command="nonexistent_xyz")
        assert not provider.is_available

def test_external_cli_available():
    with patch("live2note.llm.external_cli.shutil.which", return_value="/usr/bin/python"):
        provider = ExternalCLIProvider(command="python")
        assert provider.is_available

def test_external_cli_name():
    provider = ExternalCLIProvider(command="claude -p --verbose")
    assert "external_cli" in provider.name
    assert "claude -p" in provider.name

def test_external_cli_generate_success():
    with patch("live2note.llm.external_cli.shutil.which", return_value="/usr/bin/echo"):
        with patch("live2note.llm.external_cli.subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.stdout = "Hello from CLI"
            mock_proc.stderr = ""
            mock_proc.returncode = 0
            mock_run.return_value = mock_proc

            provider = ExternalCLIProvider(command="echo", args=["hello"])
            result = provider.generate("Test prompt")

            assert result.text == "Hello from CLI"
            assert result.error is None
            mock_run.assert_called_once()

def test_external_cli_generate_stdin_passed():
    with patch("live2note.llm.external_cli.shutil.which", return_value="/usr/bin/cat"):
        with patch("live2note.llm.external_cli.subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.stdout = "Received: prompt text"
            mock_proc.stderr = ""
            mock_proc.returncode = 0
            mock_run.return_value = mock_proc

            provider = ExternalCLIProvider(command="cat")
            result = provider.generate("prompt text")

            assert result.text == "Received: prompt text"
            assert mock_run.call_args[1]["input"] == "prompt text"

def test_external_cli_generate_timeout():
    with patch("live2note.llm.external_cli.shutil.which", return_value="/usr/bin/sleep"):
        with patch("live2note.llm.external_cli.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="sleep", timeout=1)

            provider = ExternalCLIProvider(command="sleep", args=["999"], timeout_seconds=1)
            result = provider.generate("test")

            assert not result.text
            assert "timed out" in result.error.lower()

def test_external_cli_generate_file_not_found():
    with patch("live2note.llm.external_cli.shutil.which", return_value="/fake/path/cmd"):
        with patch("live2note.llm.external_cli.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("No such file")

            provider = ExternalCLIProvider(command="cmd")
            result = provider.generate("test")

            assert not result.text
            assert "not found" in result.error.lower()

def test_external_cli_generate_nonzero_exit_with_stdout():
    with patch("live2note.llm.external_cli.shutil.which", return_value="/usr/bin/python"):
        with patch("live2note.llm.external_cli.subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.stdout = "Partial output"
            mock_proc.stderr = "Warning message"
            mock_proc.returncode = 1
            mock_run.return_value = mock_proc

            provider = ExternalCLIProvider(command="python", args=["script.py"])
            result = provider.generate("test")

            # Non-zero exit with stdout: should still return text.
            assert result.text == "Partial output"

def test_external_cli_generate_nonzero_exit_no_stdout():
    with patch("live2note.llm.external_cli.shutil.which", return_value="/usr/bin/false"):
        with patch("live2note.llm.external_cli.subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.stdout = ""
            mock_proc.stderr = "Fatal error occurred"
            mock_proc.returncode = 1
            mock_run.return_value = mock_proc

            provider = ExternalCLIProvider(command="false")
            result = provider.generate("test")

            assert not result.text
            assert "exited code 1" in result.error.lower()

def test_external_cli_command_not_configured():
    provider = ExternalCLIProvider(command="")
    result = provider.generate("test")
    assert not result.text
    assert "not configured" in result.error.lower()

def test_external_cli_unsupported_input_mode():
    provider = ExternalCLIProvider(command="echo", input_mode="args")
    with patch("live2note.llm.external_cli.shutil.which", return_value="/bin/echo"):
        result = provider.generate("test")
        assert not result.text
        assert "unsupported" in result.error.lower()


# ── detect_external_cli ────────────────────────────────────────

def test_detect_external_cli_found():
    with patch("live2note.llm.external_cli.shutil.which", return_value="/usr/local/bin/claude"):
        result = detect_external_cli()
        assert result == "/usr/local/bin/claude"

def test_detect_external_cli_not_found():
    with patch("live2note.llm.external_cli.shutil.which", return_value=None):
        result = detect_external_cli()
        assert result is None

def test_detect_external_cli_windows():
    with (
        patch("live2note.llm.external_cli.os.name", "nt"),
        patch("live2note.llm.external_cli.shutil.which") as mock_which,
    ):
        mock_which.side_effect = lambda x: (
            "C:\\bin\\claude.cmd" if x == "claude.cmd" else None
        )
        result = detect_external_cli()
        assert result == "C:\\bin\\claude.cmd"


# ── create_provider ────────────────────────────────────────────

class _FakeLLMConfig:
    """Minimal fake config object for testing create_provider."""
    def __init__(self, provider="auto", api_key="", api_base="", model="",
                 external_cli=None, max_tokens=4096, temperature=0.3):
        self.provider = provider
        self.api_key = api_key
        self.api_base = api_base
        self.model = model
        self.external_cli = external_cli or {}
        self.max_tokens = max_tokens
        self.temperature = temperature


def test_create_provider_none():
    cfg = _FakeLLMConfig(provider="none")
    provider = create_provider(cfg)
    assert provider.name == "none"
    result = provider.generate("test")
    assert result.text == ""

def test_create_provider_openai_with_key():
    cfg = _FakeLLMConfig(provider="openai_compatible", api_key="sk-test-key", model="gpt-4o")
    provider = create_provider(cfg)
    assert "openai_compatible" in provider.name

def test_create_provider_anthropic():
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test1234567890"}):
        provider = create_provider(_FakeLLMConfig(provider="anthropic"))
        assert "anthropic" in provider.name

def test_create_provider_external_cli_explicit():
    cfg = _FakeLLMConfig(
        provider="external_cli",
        external_cli={"enabled": True, "command": "claude -p"},
    )
    with patch("live2note.llm.provider_registry.detect_external_cli", return_value=None):
        with patch("live2note.llm.external_cli.shutil.which", return_value="/usr/bin/claude"):
            provider = create_provider(cfg)
            assert "external_cli" in provider.name
            assert provider.is_available

def test_create_provider_auto_fallback_to_external_cli():
    """When no API key, auto-detect should find external CLI."""
    cfg = _FakeLLMConfig(provider="auto", api_key="")
    with (
        patch("live2note.llm.provider_registry.detect_env",
              return_value=MagicMock(provider="none", api_key="", api_base="", model="")),
        patch("live2note.llm.provider_registry.detect_external_cli",
              return_value="/usr/bin/claude"),
        patch("live2note.llm.external_cli.shutil.which",
              return_value="/usr/bin/claude"),
    ):
        provider = create_provider(cfg)
        assert "external_cli" in provider.name

def test_create_provider_prompt_only_fallback():
    cfg = _FakeLLMConfig(provider="auto", api_key="")
    with (
        patch("live2note.llm.provider_registry.detect_env",
              return_value=MagicMock(provider="none", api_key="", api_base="", model="")),
        patch("live2note.llm.provider_registry.detect_external_cli",
              return_value=None),
    ):
        provider = create_provider(cfg, output_dir=Path("/tmp/prompts"))
        assert "prompt_only" in provider.name

def test_create_provider_none_fallback():
    cfg = _FakeLLMConfig(provider="auto", api_key="")
    with (
        patch("live2note.llm.provider_registry.detect_env",
              return_value=MagicMock(provider="none", api_key="", api_base="", model="")),
        patch("live2note.llm.provider_registry.detect_external_cli",
              return_value=None),
    ):
        provider = create_provider(cfg)
        assert provider.name == "none"

def test_create_provider_override():
    cfg = _FakeLLMConfig(
        provider="openai_compatible",
        api_key="sk-test-key",
        external_cli={"enabled": True, "command": "claude -p"},
    )
    with patch("live2note.llm.external_cli.shutil.which", return_value="/usr/bin/claude"):
        provider = create_provider(cfg, provider_override="external_cli")
        assert "external_cli" in provider.name
        assert provider.is_available


# ── BaseLLMProvider / LLMResult ────────────────────────────────

def test_llm_result_defaults():
    result = LLMResult(text="hello")
    assert result.text == "hello"
    assert result.raw == ""
    assert result.error is None
    assert result.metadata == {}

def test_llm_result_with_error():
    result = LLMResult(text="", error="something went wrong")
    assert result.text == ""
    assert result.error == "something went wrong"


# ── PromptOnlyProvider ─────────────────────────────────────────

def test_prompt_only_writes_file(tmp_path: Path):
    from live2note.llm.prompt_only import PromptOnlyProvider

    out_dir = tmp_path / "prompts"
    provider = PromptOnlyProvider(output_dir=out_dir)
    result = provider.generate("This is a test prompt", chunk_id=1, suffix="chunk")

    assert result.text == ""
    assert result.error == "pending_manual_summary"
    assert result.metadata["chunk_id"] == 1

    written = out_dir / "chunk_001_prompt.md"
    assert written.is_file()
    assert written.read_text(encoding="utf-8") == "This is a test prompt"

def test_prompt_only_no_output_dir():
    from live2note.llm.prompt_only import PromptOnlyProvider

    provider = PromptOnlyProvider(output_dir=None)
    result = provider.generate("test prompt", chunk_id=0)

    assert result.text == ""
    assert result.error == "pending_manual_summary"


# ── CLI llm-doctor ─────────────────────────────────────────────

def test_cli_llm_doctor(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner
    from live2note.cli import app

    # Patch base dir.
    def factory():
        return tmp_path / "tasks"
    monkeypatch.setattr("live2note.paths.default_base_dir", factory)
    monkeypatch.setattr("live2note.config.default_base_dir", factory)

    runner = CliRunner()
    result = runner.invoke(app, ["llm-doctor"])
    assert result.exit_code == 0
    assert "LLM Configuration Check" in result.output
    assert "Active provider" in result.output


# ── CLI llm-test --provider ────────────────────────────────────

def test_cli_llm_test_no_provider(tmp_path: Path, monkeypatch):
    """llm-test should exit 1 when provider is none (no config available)."""
    from typer.testing import CliRunner
    from live2note.cli import app
    import yaml

    # Write a config that explicitly sets provider=none.
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.yaml"
    config_file.write_text("llm:\n  provider: none\n", encoding="utf-8")

    def factory():
        return tmp_path / "tasks"
    monkeypatch.setattr("live2note.paths.default_base_dir", factory)
    monkeypatch.setattr("live2note.config.default_base_dir", factory)

    runner = CliRunner()
    result = runner.invoke(app, ["llm-test", "--prompt", "Hello", "--config", str(config_file)])
    assert result.exit_code == 1
    assert "No LLM provider" in result.output or "no" in result.output.lower()


# ── CLI process --provider ─────────────────────────────────────

def test_cli_process_with_provider_flag(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner
    from live2note.cli import app
    import json as _json

    def factory():
        return tmp_path / "tasks"
    monkeypatch.setattr("live2note.paths.default_base_dir", factory)
    monkeypatch.setattr("live2note.config.default_base_dir", factory)

    runner = CliRunner()
    runner.invoke(app, [
        "run", "https://example.com/live.m3u8", "--no-check", "--no-record",
    ])
    task_id = next((tmp_path / "tasks").iterdir()).name
    task_dir = tmp_path / "tasks" / task_id

    # Create fake transcript.
    transcripts_dir = task_dir / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    transcript = {
        "segments": [
            {"global_start": 0.0, "global_end": 10.0,
             "text": "这是一段测试文本，用于验证 --provider 参数是否正常工作。"}
        ]
    }
    (transcripts_dir / "segment_001.json").write_text(
        _json.dumps(transcript, ensure_ascii=False), encoding="utf-8"
    )

    # Use --provider external_cli with --skip-llm to verify flag is accepted.
    result = runner.invoke(app, [
        "process", task_id, "--skip-llm", "--provider", "external_cli",
    ])
    assert result.exit_code == 0
    assert "Chunks saved" in result.output


# ── CLI export-prompts ─────────────────────────────────────────

def test_cli_export_prompts(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner
    from live2note.cli import app
    import json as _json

    def factory():
        return tmp_path / "tasks"
    monkeypatch.setattr("live2note.paths.default_base_dir", factory)
    monkeypatch.setattr("live2note.config.default_base_dir", factory)

    runner = CliRunner()
    runner.invoke(app, [
        "run", "https://example.com/live.m3u8", "--no-check", "--no-record",
    ])
    task_id = next((tmp_path / "tasks").iterdir()).name
    task_dir = tmp_path / "tasks" / task_id

    # Create fake chunks.
    chunks_dir = task_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    chunks_data = [
        {"chunk_id": 0, "start": 0.0, "end": 10.0,
         "text": "测试内容", "source_segments": [0]}
    ]
    (chunks_dir / "chunks.json").write_text(
        _json.dumps(chunks_data, ensure_ascii=False), encoding="utf-8"
    )

    result = runner.invoke(app, ["export-prompts", task_id])
    assert result.exit_code == 0
    assert "Exported" in result.output

    prompts_dir = task_dir / "prompts"
    prompt_file = prompts_dir / "chunk_000_prompt.md"
    assert prompt_file.is_file()
