"""Heuristic highlight detection from transcription segments."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


REACTION_PHRASES = (
    "oh my god",
    "no way",
    "let's go",
    "lets go",
    "what just happened",
    "unbelievable",
    "insane",
    "incredible",
    "amazing",
    "incroyable",
    "impossible",
    "attendez",
    "regardez",
    "clip",
    "clipez",
    "clipe",
)


class HighlightAnalysisError(RuntimeError):
    """Raised when a transcription cannot be analyzed."""


def _repeated_words(text: str) -> int:
    words = re.findall(r"[\w']+", text.lower())
    counts: dict[str, int] = {}
    for word in words:
        counts[word] = counts.get(word, 0) + 1
    return sum(count - 1 for count in counts.values() if count > 1)


def _score_segment(text: str, start: float, end: float) -> float:
    normalized = text.lower()
    score = 0.0
    duration = max(0.0, end - start)

    if 3.0 <= duration <= 45.0:
        score += 0.5
    elif duration > 45.0:
        score += 0.25

    score += sum(2.0 for phrase in REACTION_PHRASES if phrase in normalized)
    score += min(text.count("!") * 0.75, 2.25)
    score += min(text.count("?") * 0.5, 1.5)
    score += min(_repeated_words(text) * 0.5, 1.5)

    return round(score, 2)


def analyze_transcription(
    segments: list[dict[str, Any]],
    max_candidates: int | None = None,
) -> list[dict[str, float]]:
    """Return timestamped candidate highlights scored with simple heuristics."""
    candidates: list[dict[str, float]] = []
    for segment in segments:
        try:
            start = float(segment["start"])
            end = float(segment["end"])
            text = str(segment.get("text", "")).strip()
        except (KeyError, TypeError, ValueError) as error:
            raise HighlightAnalysisError("Segment de transcription invalide.") from error

        if end <= start or not text:
            continue

        score = _score_segment(text, start, end)
        if score <= 0:
            continue
        candidates.append({"start": start, "end": end, "score": score})

    candidates.sort(key=lambda candidate: (-candidate["score"], candidate["start"]))
    if max_candidates is not None:
        candidates = candidates[:max(0, max_candidates)]
    return candidates


def load_transcription(input_path: Path) -> list[dict[str, Any]]:
    """Load a transcription JSON file."""
    try:
        data = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HighlightAnalysisError(
            f"Impossible de lire la transcription : {input_path}"
        ) from error

    if not isinstance(data, list):
        raise HighlightAnalysisError("La transcription doit etre une liste de segments.")
    return data


def save_highlights(candidates: list[dict[str, float]], output_path: Path) -> None:
    """Save highlight candidates as UTF-8 JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
