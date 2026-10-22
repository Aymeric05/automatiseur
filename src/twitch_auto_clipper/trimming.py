"""Where each Short starts and ends, chosen by Gemini from the timestamped transcript.

A Short must open on the context needed to understand it and end on its
punchline or the end of the reaction, never in the middle of a sentence or a
story. Gemini reads the sentences around each moment, with their times, picks
both bounds among them, and says when a moment cannot stand alone.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .gemini_evaluation import GEMINI_FALLBACK_MODELS, _generate_json

WINDOW_SECONDS = 35.0  # sentences shown before and after each moment
MIN_SECONDS = 15.0
MAX_SECONDS = 58.0  # a Short stays under a minute, cold open included
TRIM_SCHEMA = {
    "type": "object",
    "properties": {
        "moments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "complete": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
                "required": ["id", "start", "end", "complete"],
            },
        }
    },
    "required": ["moments"],
}


def trim_moments(
    moments: list[dict[str, Any]],
    sentences: list[dict[str, Any]],
    streamer: str = "",
    model: str = "gemini-3.6-flash",
    quota_dir: Path | None = None,
    daily_limit: int = 20,
    fallback_models: tuple[str, ...] = GEMINI_FALLBACK_MODELS,
) -> list[dict[str, Any] | None]:
    """Per moment, its new ``start``/``end`` (and ``trim_reason``), or None when Gemini finds
    it cannot be understood alone. One request for all the moments of a VOD."""
    context = []
    for index, moment in enumerate(moments, start=1):
        start = float(moment.get("highlight_start", moment["start"]))
        end = float(moment.get("highlight_end", moment["end"]))
        context.append({
            "id": f"m{index}",
            "moment": [round(start, 1), round(end, 1)],
            "title": moment.get("gemini_title") or "",
            "sentences": [
                [round(s["start"], 1), round(s["end"], 1), s["text"]]
                for s in sentences
                if s["end"] > start - WINDOW_SECONDS and s["start"] < end + WINDOW_SECONDS
            ],
        })
    prompt = (
        (f"Streamer : {streamer}. " if streamer else "")
        + "Chaque moment ci-dessous deviendra un YouTube Short. sentences liste les phrases "
        "dites autour du moment, [debut, fin, texte] en secondes. Pour chaque moment, choisis "
        "start (le debut d'une phrase de la liste) et end (la fin d'une phrase de la liste) pour "
        "que le Short se comprenne seul et soit satisfaisant : il commence juste assez tot pour "
        "donner le contexte (ce qui declenche la situation, la question posee, le debut de "
        "l'histoire), sans longue introduction inutile, et il finit sur la chute, la reponse ou la "
        f"fin de la reaction, jamais au milieu d'une phrase ni d'une histoire. Duree entre "
        f"{MIN_SECONDS:.0f} et {MAX_SECONDS:.0f} secondes, le plus court possible tant que c'est "
        "complet. complete vaut false si, meme avec les meilleures bornes, le moment ne se "
        "comprend pas sans le reste du live ou n'a pas de vraie chute. reason explique en une "
        'phrase courte. Retourne un JSON {"moments":[{"id":"m1","start":0,"end":0,'
        '"complete":true,"reason":"..."}]} avec exactement les id fournis.\n\n'
        + json.dumps(context, ensure_ascii=False)
    )
    text, _ = _generate_json(prompt, TRIM_SCHEMA, model, quota_dir, daily_limit, fallback_models)
    return parse_trims(text, moments, sentences)


def parse_trims(
    text: str, moments: list[dict[str, Any]], sentences: list[dict[str, Any]]
) -> list[dict[str, Any] | None]:
    """Gemini's bounds, snapped to the sentences and kept within the Short limits.

    A moment Gemini left out or answered badly keeps its bounds ({}); one it
    finds incomplete is None (not rendered).
    """
    found: list[dict[str, Any] | None] = [{} for _ in moments]
    try:
        answers = json.loads(text).get("moments")
    except (json.JSONDecodeError, AttributeError):
        return found
    starts = sorted(s["start"] for s in sentences)
    ends = sorted(s["end"] for s in sentences)
    for answer in answers if isinstance(answers, list) else []:
        if not isinstance(answer, dict) or not str(answer.get("id", "")).startswith("m"):
            continue
        try:
            index = int(str(answer["id"])[1:]) - 1
            start, end = float(answer["start"]), float(answer["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if not 0 <= index < len(moments):
            continue
        if answer.get("complete") is False:
            found[index] = None
            continue
        # Snapped to the nearest real sentence bounds (Gemini may round the times).
        start = min(starts, key=lambda value: abs(value - start), default=start)
        end = min(ends, key=lambda value: abs(value - end), default=end)
        if end - start < MIN_SECONDS:
            end = next((value for value in ends if value - start >= MIN_SECONDS), start + MIN_SECONDS)
        if end - start > MAX_SECONDS or end <= start:
            continue  # unusable answer: the moment keeps its bounds
        found[index] = {"start": round(start, 2), "end": round(end, 2), "trim_reason": answer.get("reason")}
    return found
