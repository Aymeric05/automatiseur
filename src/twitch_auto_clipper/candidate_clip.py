"""Generate a vertical clip from a saved highlight candidate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .subtitles import generate_ass_subtitles
from .video import create_vertical_clip, get_video_duration


class CandidateClipError(RuntimeError):
    """Raised when a candidate cannot be turned into a clip."""


def load_candidate(candidates_path: Path, candidate_index: int) -> dict[str, Any]:
    """Load one zero-based candidate from a highlights JSON list."""
    try:
        data = json.loads(candidates_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CandidateClipError(
            f"Impossible de lire les candidats : {candidates_path}"
        ) from error

    if not isinstance(data, list):
        raise CandidateClipError("Le fichier de candidats doit contenir une liste JSON.")
    if candidate_index < 0 or candidate_index >= len(data):
        raise CandidateClipError(
            f"Index candidat invalide : {candidate_index} (1 a {len(data)})."
        )
    candidate = data[candidate_index]
    if not isinstance(candidate, dict):
        raise CandidateClipError("Le candidat selectionne doit etre un objet JSON.")
    return candidate


def calculate_candidate_bounds(
    candidate: dict[str, Any], duration: float, before: float = 5.0, after: float = 5.0
) -> tuple[float, float]:
    """Calculate candidate bounds with margins, clamped to video duration."""
    if before < 0 or after < 0:
        raise CandidateClipError("Les marges before et after doivent etre positives ou nulles.")
    try:
        candidate_start = float(candidate["start"])
        candidate_end = float(candidate["end"])
    except (KeyError, TypeError, ValueError) as error:
        raise CandidateClipError("Le candidat doit contenir start et end valides.") from error
    if candidate_end <= candidate_start:
        raise CandidateClipError("La fin du candidat doit etre superieure au debut.")
    if duration <= 0:
        raise CandidateClipError("La duree de la video doit etre positive.")

    start = max(0.0, candidate_start - before)
    end = min(duration, candidate_end + after)
    if start >= duration or end <= start:
        raise CandidateClipError("Le candidat est en dehors de la duree de la video.")
    return start, end


def generate_clip_from_candidate(
    source_path: Path,
    candidates_path: Path,
    candidate_index: int,
    output_path: Path,
    transcript_path: Path | None = None,
    before: float = 5.0,
    after: float = 5.0,
) -> tuple[Path, float, float]:
    """Generate one vertical clip and optionally burn existing transcript words."""
    candidate = load_candidate(candidates_path, candidate_index)
    duration = get_video_duration(source_path)
    start, end = calculate_candidate_bounds(candidate, duration, before, after)

    subtitles_path = None
    if transcript_path is not None:
        try:
            segments = json.loads(transcript_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CandidateClipError(
                f"Impossible de lire la transcription : {transcript_path}"
            ) from error
        if not isinstance(segments, list):
            raise CandidateClipError("La transcription doit contenir une liste JSON.")
        subtitles_path = output_path.with_suffix(".ass")
        generate_ass_subtitles(segments, subtitles_path, clip_start=start, clip_end=end)

    create_vertical_clip(source_path, output_path, start, end, subtitles_path=subtitles_path)
    return output_path, start, end
