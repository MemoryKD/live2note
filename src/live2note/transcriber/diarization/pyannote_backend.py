"""Pyannote.audio speaker diarization backend.

pyannote.audio is an optional dependency — import errors are caught
gracefully and reported via is_available.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from live2note.logger import get_logger

log = get_logger("diarization.pyannote")


@dataclass(frozen=True)
class DiarizationSegment:
    """A single speaker segment from the diarization pipeline."""

    start: float
    end: float
    speaker: str


class PyannoteDiarizer:
    """Wraps pyannote.audio's SpeakerDiarization pipeline.

    Usage:
        diarizer = PyannoteDiarizer(auth_token="hf_...")
        if diarizer.is_available:
            segments = diarizer.diarize(audio_path)
    """

    def __init__(
        self,
        model: str = "pyannote/speaker-diarization-3.1",
        device: str = "auto",
        auth_token: str = "",
        num_speakers: int = 0,
    ) -> None:
        self._model_name = model
        self._device = device
        self._auth_token = auth_token
        self._num_speakers = num_speakers
        self._pipeline: Any = None
        self._load_error: str | None = None

    def _ensure_pipeline(self) -> Any | None:
        if self._pipeline is not None:
            return self._pipeline
        if self._load_error:
            return None

        try:
            from pyannote.audio import Pipeline
        except ImportError as exc:
            self._load_error = (
                "pyannote.audio is not installed. "
                "Install it: pip install pyannote.audio"
            )
            log.warning(self._load_error)
            return None

        try:
            log.info("Loading diarization pipeline: %s", self._model_name)
            self._pipeline = Pipeline.from_pretrained(
                self._model_name,
                use_auth_token=self._auth_token or None,
            )
            if self._device != "auto":
                self._pipeline.to(self._device)
            log.info("Diarization pipeline loaded.")
        except Exception as exc:
            self._load_error = f"Failed to load diarization pipeline: {exc}"
            log.error(self._load_error)
            return None

        return self._pipeline

    @property
    def is_available(self) -> bool:
        self._ensure_pipeline()
        return self._pipeline is not None

    @property
    def load_error(self) -> str | None:
        return self._load_error

    def diarize(self, audio_path: Path) -> list[DiarizationSegment]:
        """Run speaker diarization on an audio file.

        Args:
            audio_path: Path to a WAV audio file.

        Returns:
            List of DiarizationSegment sorted by start time.
        """
        pipeline = self._ensure_pipeline()
        if pipeline is None:
            msg = self._load_error or "Diarization pipeline not available"
            raise RuntimeError(msg)

        if not audio_path.is_file():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        log.info("Diarizing: %s", audio_path.name)

        kwargs: dict[str, Any] = {}
        if self._num_speakers > 0:
            kwargs["num_speakers"] = self._num_speakers

        diarization = pipeline(str(audio_path), **kwargs)

        segments: list[DiarizationSegment] = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            segments.append(
                DiarizationSegment(
                    start=round(turn.start, 3),
                    end=round(turn.end, 3),
                    speaker=speaker,
                )
            )

        segments.sort(key=lambda s: s.start)
        log.info(
            "Diarized %d segments, %d speakers",
            len(segments),
            len({s.speaker for s in segments}),
        )
        return segments
