"""Where the important part of a screen-sharing stream is, to center its Shorts on it.

A Short keeps only a vertical strip of about a third of the stream's width.
When the streamer shows their screen, what matters (the video, the chart, the
game) is often off-center, pushed aside by the chat, a facecam or other
windows; Gemini looks at one low-res frame per moment and says where it is.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

from .gemini_evaluation import GEMINI_FALLBACK_MODELS, _generate_json
from .twitch import resolve_twitch_video_url

FOCUS_MODEL = "gemini-flash-lite-latest"  # spares the main model's quota for the selections
FRAME_HEIGHT = 360  # low-res rendition: a few MB for all the frames of a VOD
FRAME_SIZE = "480:270"
# Twitch categories filmed with a camera: their Shorts stay centered.
IRL_CATEGORIES = frozenset({
    "irl", "travel & outdoors", "food & drink", "fitness & health", "pools, hot tubs, and beaches",
})
FOCUS_SCHEMA = {
    "type": "object",
    "properties": {
        "frames": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "scene": {"type": "string", "enum": ["screen", "camera"]},
                    "box_2d": {"type": "array", "items": {"type": "number"}},
                },
                "required": ["index", "scene", "box_2d"],
            },
        }
    },
    "required": ["frames"],
}
PROMPT = (
    "Chaque image vient d'un live Twitch. Le Short sera un recadrage vertical 9:16 qui ne garde "
    "qu'une bande verticale d'environ un tiers de la largeur de l'image, sur toute sa hauteur : "
    "il faut choisir ou la placer. Pour chaque image, donne la boite box_2d [ymin, xmin, ymax, xmax] "
    "(normalisee de 0 a 1000), la plus serree possible, de l'element que le spectateur doit voir : "
    "ce que le streamer montre et commente (la personne qui parle dans la video, le graphique, la "
    "question, le produit, le personnage du joueur ou l'action du jeu), pas toute la fenetre ni "
    "toute la page. Ce n'est jamais le chat, les notifications, la barre du navigateur ou des "
    "taches, les marges vides, ni la webcam du streamer placee dans un coin ou a cote de ce qu'il "
    'montre. scene vaut "screen" quand le streamer montre son ecran (jeu, navigateur, video), '
    '"camera" quand l\'image est la webcam du streamer en plein cadre ou une scene filmee en IRL '
    "(la boite couvre alors la personne ou l'action filmee). Retourne un JSON "
    '{"frames":[{"index":1,"scene":"screen","box_2d":[0,0,1000,1000]}]}.'
)


def find_focus(
    vod_id: str,
    times: list[float],
    model: str = FOCUS_MODEL,
    quota_dir: Path | None = None,
    daily_limit: int = 20,
    fallback_models: tuple[str, ...] = GEMINI_FALLBACK_MODELS,
) -> list[float | None]:
    """Horizontal center (0 to 1) of what matters at each time of the VOD, in one request.

    None for a frame filmed with a camera (webcam in full frame, IRL): that
    Short stays centered.
    """
    from google.genai import types

    url = resolve_twitch_video_url(f"https://www.twitch.tv/videos/{vod_id}", max_height=FRAME_HEIGHT)
    contents: list[Any] = [PROMPT]
    for index, seconds in enumerate(times, start=1):
        frame = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", str(seconds), "-i", url, "-frames:v", "1",
             "-vf", f"scale={FRAME_SIZE}", "-f", "mjpeg", "-"],
            stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=120,
        ).stdout
        contents += [f"Image {index} :", types.Part.from_bytes(data=frame, mime_type="image/jpeg")]
    text, _ = _generate_json(contents, FOCUS_SCHEMA, model, quota_dir, daily_limit, fallback_models)
    return parse_focus(text, len(times))


def parse_focus(text: str, count: int) -> list[float | None]:
    """The centers of the screen frames' boxes in Gemini's answer (None when missing or invalid)."""
    centers: list[float | None] = [None] * count
    try:
        frames = json.loads(text).get("frames")
    except (json.JSONDecodeError, AttributeError):
        return centers
    for item in frames if isinstance(frames, list) else []:
        if not isinstance(item, dict) or item.get("scene") != "screen":
            continue
        index, box = item.get("index"), item.get("box_2d")
        if (
            isinstance(index, int) and 1 <= index <= count
            and isinstance(box, list) and len(box) == 4
            and all(isinstance(value, (int, float)) for value in box)
            and 0 <= box[1] < box[3] <= 1000
        ):
            centers[index - 1] = round((box[1] + box[3]) / 2000, 3)
    return centers
