"""Who speaks in each Short: the streamer and the people with them, or a watched video.

The subtitles show only what the streamer and the people talking with them say,
never a video, a clip or a game they are watching (it often has its own
captions, cut by the crop, and its words are not theirs). Gemini listens to
each moment's audio and says which of its sentences come from such a source.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

from .gemini_evaluation import GEMINI_FALLBACK_MODELS, _generate_json

MARGIN_SECONDS = 2.0  # audio heard before and after the moment (the Short's render margins)
AUDIO_BITRATE = "48k"  # mono MP3: about 6 KB a second, 20 moments fit in one request

SPEAKERS_SCHEMA = {
    "type": "object",
    "properties": {
        "moments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "media": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["id", "media"],
            },
        }
    },
    "required": ["moments"],
}

PROMPT = (
    "Chaque audio vient d'un live Twitch et deviendra un YouTube Short. Pour chacun, sentences "
    "numerote les phrases transcrites, [numero, debut, fin, texte] en secondes du live. Ecoute "
    "l'audio et donne dans media les numeros des phrases qui ne sont PAS dites par le streamer "
    "ou par les personnes qui parlent avec lui (dans la piece, en vocal ou en appel), mais qui "
    "viennent de ce qu'il regarde ou joue : une video, un clip, une emission, un film, la voix "
    "d'un personnage ou une cinematique de jeu, un message lu par une synthese vocale. Les "
    "phrases du streamer qui commente ou repete ce qu'il voit ne sont pas media. Liste vide si "
    'tout est dit par le streamer et son entourage. Retourne un JSON {"moments":[{"id":"m1",'
    '"media":[2,3]}]} avec exactement les id fournis.'
)


def media_speech(
    audio_path: Path,
    moments: list[dict[str, Any]],
    sentences: list[dict[str, Any]],
    model: str,
    quota_dir: Path | None = None,
    daily_limit: int = 20,
    fallback_models: tuple[str, ...] = GEMINI_FALLBACK_MODELS,
) -> list[list[list[float]]]:
    """Per moment, the spans [start, end] (live seconds) said by a watched video or game."""
    from google.genai import types

    contents: list[Any] = [PROMPT]
    numbered = []
    for index, moment in enumerate(moments, start=1):
        start = max(0.0, float(moment["start"]) - MARGIN_SECONDS)
        end = float(moment["end"]) + MARGIN_SECONDS
        audio = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", str(start), "-t", str(end - start), "-i", str(audio_path),
             "-vn", "-ac", "1", "-b:a", AUDIO_BITRATE, "-f", "mp3", "-"],
            stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=120,
        ).stdout
        inside = [s for s in sentences if s["end"] > start and s["start"] < end]
        numbered.append(inside)
        contents += [
            json.dumps({"id": f"m{index}", "audio_start": round(start, 1), "sentences": [
                [number, round(s["start"], 1), round(s["end"], 1), s["text"]]
                for number, s in enumerate(inside, start=1)
            ]}, ensure_ascii=False),
            types.Part.from_bytes(data=audio, mime_type="audio/mp3"),
        ]
    text, _ = _generate_json(contents, SPEAKERS_SCHEMA, model, quota_dir, daily_limit, fallback_models)
    return parse_media(text, numbered)


def parse_media(text: str, numbered: list[list[dict[str, Any]]]) -> list[list[list[float]]]:
    """The spans of the sentences Gemini marked as media, per moment; none when unreadable."""
    found: list[list[list[float]]] = [[] for _ in numbered]
    try:
        items = json.loads(text).get("moments")
    except (json.JSONDecodeError, AttributeError):
        return found
    for item in items if isinstance(items, list) else []:
        try:
            index = int(str(item["id"]).lstrip("m")) - 1
            numbers = [int(number) for number in item.get("media") or []]
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= index < len(numbered):
            sentences = numbered[index]
            found[index] = [
                [float(sentences[n - 1]["start"]), float(sentences[n - 1]["end"])]
                for n in numbers if 1 <= n <= len(sentences)
            ]
    return found
