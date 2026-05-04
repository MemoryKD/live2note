"""Configuration loading, validation, and defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from live2note.paths import config_search_paths, default_base_dir

_DEFAULTS: dict[str, Any] = {
    "recording": {
        "segment_duration": 5,
        "audio_format": "wav",
        "audio_sample_rate": 16000,
        "audio_channels": 1,
        "ffmpeg_path": "ffmpeg",
        "stop_grace_seconds": 10,
        "no_data_timeout_seconds": 180,
        "live_check_interval_seconds": 60,
        "max_live_check_failures": 3,
    },
    "transcription": {
        "model_size": "large-v3",
        "language": "zh",
        "device": "auto",
        "compute_type": "auto",
        "beam_size": 5,
        "vad_filter": True,
    },
    "llm": {
        "provider": "external_cli",
        "model": "gpt-4o",
        "api_base": "https://api.openai.com/v1",
        "api_key": "",
        "api_key_env": "",
        "temperature": 0.3,
        "max_tokens": 4096,
        "summary_model": "",
        "auto_detect_env": True,
        "external_cli": {
            "enabled": True,
            "command": "claude",
            "args": ["-p"],
            "timeout_seconds": 600,
            "input_mode": "stdin",
            "output_mode": "stdout",
            "fallback_to_prompt_only": True,
        },
        "prompt_only": {
            "enabled": True,
            "output_dir": "prompts",
        },
        "openai_compatible": {
            "enabled": False,
            "api_base": "https://api.openai.com/v1",
            "model": "gpt-4o",
            "api_key_env": "OPENAI_API_KEY",
        },
        "anthropic": {
            "enabled": False,
            "model": "claude-sonnet-4-20250514",
            "api_key_env": "ANTHROPIC_API_KEY",
        },
    },
    "getnote": {
        "enabled": False,
        "command": "getnote save",
        "default_tags": ["live2note"],
        "timeout": 60,
    },
    "output": {
        "base_dir": "",
        "keep_audio": True,
        "keep_intermediate": True,
    },
    "platforms": {
        "bilibili": {"quality": "best"},
        "douyin": {"quality": "best"},
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning a new dict."""
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


@dataclass(frozen=True)
class RecordingConfig:
    segment_duration: int = 5
    audio_format: str = "wav"
    audio_sample_rate: int = 16000
    audio_channels: int = 1
    ffmpeg_path: str = "ffmpeg"
    stop_grace_seconds: int = 10
    no_data_timeout_seconds: int = 180
    live_check_interval_seconds: int = 60
    max_live_check_failures: int = 3


@dataclass(frozen=True)
class TranscriptionConfig:
    model_size: str = "large-v3"
    language: str = "zh"
    device: str = "auto"
    compute_type: str = "auto"
    beam_size: int = 5
    vad_filter: bool = True


@dataclass(frozen=True)
class LLMConfig:
    provider: str = "external_cli"
    model: str = "gpt-4o"
    api_base: str = "https://api.openai.com/v1"
    api_key: str = ""
    api_key_env: str = ""
    temperature: float = 0.3
    max_tokens: int = 4096
    summary_model: str = ""
    auto_detect_env: bool = True
    external_cli: dict = field(default_factory=lambda: {
        "enabled": True,
        "command": "claude",
        "args": ["-p"],
        "timeout_seconds": 600,
        "input_mode": "stdin",
        "output_mode": "stdout",
        "fallback_to_prompt_only": True,
    })
    prompt_only: dict = field(default_factory=lambda: {
        "enabled": True,
        "output_dir": "prompts",
    })
    openai_compatible: dict = field(default_factory=lambda: {
        "enabled": False,
    })
    anthropic: dict = field(default_factory=lambda: {
        "enabled": False,
    })


@dataclass(frozen=True)
class GetnoteConfig:
    enabled: bool = False
    command: str = "getnote save"
    default_tags: tuple[str, ...] = ("live2note",)
    timeout: int = 60


@dataclass(frozen=True)
class OutputConfig:
    base_dir: Path = field(default_factory=default_base_dir)
    keep_audio: bool = True
    keep_intermediate: bool = True


@dataclass(frozen=True)
class AppConfig:
    recording: RecordingConfig = field(default_factory=RecordingConfig)
    transcription: TranscriptionConfig = field(default_factory=TranscriptionConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    getnote: GetnoteConfig = field(default_factory=GetnoteConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    platforms: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AppConfig:
        rec = raw.get("recording", {})
        tr = raw.get("transcription", {})
        llm = raw.get("llm", {})
        gn = raw.get("getnote", {})
        out = raw.get("output", {})

        base_dir_str = out.get("base_dir", "")
        base_dir = Path(base_dir_str).expanduser() if base_dir_str else default_base_dir()

        # Env var overrides for secrets.
        llm_key = llm.get("api_key", "") or os.environ.get("LLM_API_KEY", "")
        llm["api_key"] = llm_key

        return cls(
            recording=RecordingConfig(**rec),
            transcription=TranscriptionConfig(**tr),
            llm=LLMConfig(**{k: v for k, v in llm.items() if k in LLMConfig.__dataclass_fields__}),
            getnote=GetnoteConfig(
                enabled=gn.get("enabled", False),
                command=gn.get("command", GetnoteConfig.command),
                default_tags=tuple(gn.get("default_tags", ["live2note"])),
                timeout=gn.get("timeout", 60),
            ),
            output=OutputConfig(
                base_dir=base_dir,
                keep_audio=out.get("keep_audio", True),
                keep_intermediate=out.get("keep_intermediate", True),
            ),
            platforms=raw.get("platforms", {}),
        )


def load_config(path: Path | None = None) -> AppConfig:
    """Load config from the given path, or search default locations.

    Returns defaults if no config file is found.
    """
    if path is not None:
        return _load_file(path)

    for candidate in config_search_paths():
        if candidate.is_file():
            return _load_file(candidate)

    return AppConfig.from_dict(_DEFAULTS)


def _load_file(path: Path) -> AppConfig:
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    merged = _deep_merge(_DEFAULTS, raw)
    return AppConfig.from_dict(merged)


def init_config(output_path: Path | None = None) -> Path:
    """Write the example config to the given path (or default location)."""
    target = output_path or (Path.home() / ".live2note" / "config.yaml")
    target.parent.mkdir(parents=True, exist_ok=True)
    content = yaml.dump(_DEFAULTS, default_flow_style=False, allow_unicode=True, sort_keys=False)
    target.write_text(content, encoding="utf-8")
    return target


def config_summary(cfg: AppConfig) -> str:
    """Return a human-readable one-line summary of key config values."""
    parts = [
        f"segment={cfg.recording.segment_duration}min",
        f"model={cfg.transcription.model_size}",
        f"lang={cfg.transcription.language}",
        f"llm={cfg.llm.model}",
        f"getnote={'on' if cfg.getnote.enabled else 'off'}",
        f"output={cfg.output.base_dir}",
    ]
    return " | ".join(parts)
