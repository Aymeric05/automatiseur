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
    "what the",
    "are you serious",
    "oh no",
    "holy",
    "unbelievable",
    "insane",
    "incredible",
    "amazing",
    "haha",
    "lmao",
    "incroyable",
    "impossible",
    "attendez",
    "regardez",
    "clip it",
    "clip that",
    "clipez",
    "clipe",
)
# Words that open a new topic: a natural place for a Short to start.
TOPIC_OPENERS = ("okay so", "ok so", "anyway", "wait", "so basically", "guys", "chat")

SENTENCE_JOIN_GAP = 1.5  # merge Whisper segments into one sentence below this pause
CONTEXT_GAP = 1.5  # previous sentence is kept as lead-in context below this pause
MIN_CANDIDATE_SECONDS = 12.0
MAX_CANDIDATE_SECONDS = 40.0
MAX_OVERLAP_RATIO = 0.25  # of the shorter candidate


class HighlightAnalysisError(RuntimeError):
    """Raised when a transcription cannot be analyzed."""


def _words(text: str) -> list[str]:
    return re.findall(r"[\w']+", text.lower())


def _has_phrase(normalized: str, phrase: str) -> bool:
    return re.search(rf"\b{re.escape(phrase)}\b", normalized) is not None


def split_sentences(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge Whisper segments into sentences using punctuation and pauses.

    A segment continues the previous sentence when that sentence has no final
    punctuation or when the segment starts in lowercase, as long as the pause
    between them is short.
    """
    sentences: list[dict[str, Any]] = []
    for segment in segments:
        try:
            start = float(segment["start"])
            end = float(segment["end"])
            text = str(segment.get("text", "")).strip()
        except (KeyError, TypeError, ValueError) as error:
            raise HighlightAnalysisError("Segment de transcription invalide.") from error
        if end <= start or not text:
            continue
        previous = sentences[-1] if sentences else None
        if (
            previous is not None
            and start - previous["end"] < SENTENCE_JOIN_GAP
            and (previous["text"][-1] not in ".!?" or text[0].islower())
        ):
            previous["end"] = end
            previous["text"] = f"{previous['text']} {text}"
        else:
            sentences.append({"start": start, "end": end, "text": text})
    return sentences


def _score_sentence(text: str, start: float, end: float, typical_rate: float) -> float:
    normalized = text.lower()
    words = _words(text)
    score = min(2.0 * sum(_has_phrase(normalized, p) for p in REACTION_PHRASES), 4.0)
    score += min(text.count("!") * 0.75, 1.5)
    score += min(text.count("?") * 0.5, 1.0)
    # Emphatic repetition ("no no no"), not any repeated filler word.
    if any(words[i] == words[i + 1] == words[i + 2] for i in range(len(words) - 2)):
        score += 1.0
    # Fast speech usually means excitement.
    duration = end - start
    if typical_rate and duration >= 1.0 and len(words) / duration >= 1.3 * typical_rate:
        score += 1.0
    return score


def _overlap_ratio(a: dict[str, float], b: dict[str, float]) -> float:
    overlap = min(a["end"], b["end"]) - max(a["start"], b["start"])
    shorter = min(a["end"] - a["start"], b["end"] - b["start"])
    return max(0.0, overlap) / shorter if shorter > 0 else 0.0


def analyze_transcription(
    segments: list[dict[str, Any]],
    max_candidates: int | None = None,
) -> list[dict[str, float]]:
    """Return sentence-aligned candidate highlights, best first.

    Each candidate is built around an interesting sentence (the "highlight",
    kept in ``highlight_start``/``highlight_end``). It starts at the beginning
    of that sentence, or of the sentence just before it when it directly leads
    in, and grows with following sentences until it lasts at least
    ``MIN_CANDIDATE_SECONDS``. Candidates overlapping a better one are dropped.
    """
    sentences = split_sentences(segments)
    rates = sorted(
        len(_words(s["text"])) / (s["end"] - s["start"])
        for s in sentences
        if s["end"] - s["start"] >= 1.0
    )
    typical_rate = rates[len(rates) // 2] if rates else 0.0
    scores = [_score_sentence(s["text"], s["start"], s["end"], typical_rate) for s in sentences]

    windows: list[dict[str, float]] = []
    for anchor, sentence in enumerate(sentences):
        if scores[anchor] <= 0:
            continue
        first = anchor
        if anchor > 0 and sentence["start"] - sentences[anchor - 1]["end"] < CONTEXT_GAP:
            first = anchor - 1
        last = anchor
        while (
            last + 1 < len(sentences)
            and sentences[last]["end"] - sentences[first]["start"] < MIN_CANDIDATE_SECONDS
            and sentences[last + 1]["end"] - sentences[first]["start"] <= MAX_CANDIDATE_SECONDS
            and sentences[last + 1]["start"] - sentences[last]["end"] < 3.0
        ):
            last += 1
        members = range(first, last + 1)
        score = sum(scores[i] for i in members)
        # A question answered inside the window is an exchange.
        if any(sentences[i]["text"].endswith("?") for i in members if i < last):
            score += 0.5
        opener = sentences[first]["text"].lower()
        gap_before = sentences[first]["start"] - sentences[first - 1]["end"] if first else 99.0
        if gap_before > 2.0 or any(opener.startswith(word) for word in TOPIC_OPENERS):
            score += 0.5  # natural start: pause or topic change
        windows.append({
            "start": sentences[first]["start"],
            "end": sentences[last]["end"],
            "score": round(score, 2),
            "highlight_start": sentence["start"],
            "highlight_end": sentence["end"],
        })

    windows.sort(key=lambda window: (-window["score"], window["start"]))
    candidates: list[dict[str, float]] = []
    for window in windows:
        if all(_overlap_ratio(window, kept) <= MAX_OVERLAP_RATIO for kept in candidates):
            candidates.append(window)
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
