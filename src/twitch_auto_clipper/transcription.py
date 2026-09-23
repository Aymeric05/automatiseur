"""Whisper transcription helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class TranscriptionError(RuntimeError):
    """Raised when a video cannot be transcribed."""


def _get_whisper_model(model_size: str, device: str, compute_type: str):
    try:
        from faster_whisper import WhisperModel
    except ModuleNotFoundError as error:
        raise TranscriptionError(
            "faster-whisper est requis pour transcrire une video."
        ) from error

    return WhisperModel(model_size, device=device, compute_type=compute_type)


def _serialize_word(word: Any) -> dict[str, Any]:
    return {
        "word": str(getattr(word, "word", "")),
        "start": float(getattr(word, "start", 0.0)),
        "end": float(getattr(word, "end", 0.0)),
    }


def _serialize_segment(segment: Any) -> dict[str, Any]:
    words = getattr(segment, "words", None) or []
    return {
        "start": float(segment.start),
        "end": float(segment.end),
        "text": str(segment.text).strip(),
        "words": [_serialize_word(word) for word in words],
    }


def transcribe_video(
    input_path: Path,
    model_size: str = "base",
    language: str | None = None,
    device: str = "cpu",
    compute_type: str = "int8",
) -> list[dict[str, Any]]:
    """Transcribe a video using CPU/int8 by default."""
    if not input_path.is_file():
        raise TranscriptionError(f"Fichier video introuvable : {input_path}")

    try:
        model = _get_whisper_model(model_size, device, compute_type)
        segments, _ = model.transcribe(
            str(input_path),
            language=language,
            word_timestamps=True,
        )
        return [_serialize_segment(segment) for segment in segments]
    except TranscriptionError:
        raise
    except Exception as error:
        raise TranscriptionError(f"Echec de la transcription : {error}") from error


def save_transcription(
    segments: list[dict[str, Any]], output_path: Path
) -> None:
    """Save timestamped transcription data as UTF-8 JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(segments, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
