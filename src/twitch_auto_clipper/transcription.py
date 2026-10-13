"""Whisper transcription helpers."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
from typing import Any

from .video import get_video_duration

# Whisper decodes its whole input in memory (about 2.5 GB for an 11-hour VOD):
# long files are transcribed 30 minutes at a time (about 120 MB each).
CHUNK_SECONDS = 1800.0


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


def _serialize_word(word: Any, offset: float = 0.0) -> dict[str, Any]:
    return {
        "word": str(getattr(word, "word", "")),
        "start": float(getattr(word, "start", 0.0)) + offset,
        "end": float(getattr(word, "end", 0.0)) + offset,
    }


def _serialize_segment(segment: Any, offset: float = 0.0) -> dict[str, Any]:
    words = getattr(segment, "words", None) or []
    return {
        "start": float(segment.start) + offset,
        "end": float(segment.end) + offset,
        "text": str(segment.text).strip(),
        "words": [_serialize_word(word, offset) for word in words],
    }


def _duration(input_path: Path) -> float | None:
    try:
        return get_video_duration(input_path)
    except Exception:
        return None  # unknown: transcribed in one piece


def _extract_chunk(input_path: Path, start: float, length: float, output_path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y", "-ss", str(start), "-t", str(length),
            "-i", str(input_path), "-vn", "-ac", "1", "-ar", "16000", str(output_path),
        ],
        check=True,
        capture_output=True,
        timeout=600,
    )


def transcribe_video(
    input_path: Path,
    model_size: str = "base",
    language: str | None = None,
    device: str = "cpu",
    compute_type: str = "int8",
    chunk_seconds: float = CHUNK_SECONDS,
) -> list[dict[str, Any]]:
    """Transcribe a video or audio file using CPU/int8 by default.

    The voice-activity filter skips music and silences, where Whisper tends to
    invent sentences that could otherwise end up in Short titles. Files longer
    than ``chunk_seconds`` are cut with FFmpeg and transcribed piece by piece;
    timestamps stay those of the whole file.
    """
    if not input_path.is_file():
        raise TranscriptionError(f"Fichier video introuvable : {input_path}")

    try:
        model = _get_whisper_model(model_size, device, compute_type)

        def transcribe(path: Path, offset: float) -> list[dict[str, Any]]:
            segments, _ = model.transcribe(
                str(path),
                language=language,
                word_timestamps=True,
                vad_filter=True,
            )
            return [_serialize_segment(segment, offset) for segment in segments]

        duration = _duration(input_path)
        if duration is None or duration <= chunk_seconds:
            return transcribe(input_path, 0.0)
        segments: list[dict[str, Any]] = []
        with tempfile.TemporaryDirectory() as directory:
            chunk_path = Path(directory) / "chunk.wav"
            start = 0.0
            while start < duration:
                _extract_chunk(input_path, start, chunk_seconds, chunk_path)
                segments.extend(transcribe(chunk_path, start))
                start += chunk_seconds
        return segments
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
