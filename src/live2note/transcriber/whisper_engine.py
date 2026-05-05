"""Faster-whisper transcription engine with lazy model loading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from live2note.logger import get_logger

log = get_logger("transcriber.whisper")


@dataclass(frozen=True)
class Segment:
    """A single transcribed segment from the whisper model."""

    start: float
    end: float
    text: str
    confidence: float
    speaker: str = ""


class WhisperEngine:
    """Wraps faster-whisper for local transcription.

    The model is loaded lazily on the first call to transcribe().
    """

    def __init__(
        self,
        model_size: str = "large-v3",
        language: str = "zh",
        device: str = "auto",
        compute_type: str = "auto",
        beam_size: int = 5,
        vad_filter: bool = True,
        initial_prompt: str = "",
        hotwords: str = "",
        word_timestamps: bool = False,
    ) -> None:
        self._model_size = model_size
        self._language = language
        self._device = device
        self._compute_type = compute_type
        self._beam_size = beam_size
        self._vad_filter = vad_filter
        self._initial_prompt = initial_prompt
        self._hotwords = hotwords
        self._word_timestamps = word_timestamps
        self._model: Any = None

    def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model

        log.info(
            "Loading faster-whisper model: %s (device=%s, compute=%s)",
            self._model_size,
            self._device,
            self._compute_type,
        )

        try:
            from faster_whisper import WhisperModel
        except ImportError as err:
            raise ImportError(
                "faster-whisper is not installed. "
                "Install it: pip install faster-whisper"
            ) from err

        self._model = WhisperModel(
            self._model_size,
            device=self._device,
            compute_type=self._compute_type,
        )
        log.info("Model loaded successfully.")
        return self._model

    def transcribe(self, audio_path: Path | str) -> list[Segment]:
        """Transcribe an audio file and return segments with timestamps.

        Args:
            audio_path: Path to a WAV/MP3/FLAC audio file.

        Returns:
            List of Segment objects sorted by start time.
        """
        audio_path = Path(audio_path)
        if not audio_path.is_file():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        model = self._ensure_model()

        log.info("Transcribing: %s", audio_path.name)
        transcribe_kwargs: dict[str, Any] = dict(
            language=self._language,
            beam_size=self._beam_size,
            vad_filter=self._vad_filter,
            vad_parameters=dict(min_silence_duration_ms=500),
            word_timestamps=self._word_timestamps,
        )
        if self._initial_prompt:
            transcribe_kwargs["initial_prompt"] = self._initial_prompt
        if self._hotwords:
            transcribe_kwargs["hotwords"] = self._hotwords
        segments_gen, info = model.transcribe(
            str(audio_path),
            **transcribe_kwargs,
        )

        log.info(
            "Detected language: %s (prob=%.2f)",
            info.language,
            info.language_probability,
        )

        segments: list[Segment] = []
        for seg in segments_gen:
            segments.append(
                Segment(
                    start=round(seg.start, 3),
                    end=round(seg.end, 3),
                    text=seg.text.strip(),
                    confidence=round(seg.avg_logprob, 4) if hasattr(seg, "avg_logprob") else 0.0,
                )
            )

        log.info("Transcribed %d segments from %s", len(segments), audio_path.name)
        return segments

    @property
    def is_loaded(self) -> bool:
        return self._model is not None
