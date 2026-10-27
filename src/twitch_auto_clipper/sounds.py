"""Background music and sound effects, royalty-free, renewed by the app itself.

Like the clip channels that do best (2026-10-27: 4 of 9 hits had an added
instrumental — hip-hop beat, lo-fi, dramatic orchestra, sad violin meme — and a
few a sound effect such as a cheering crowd), a Short can get a music bed under
the voices and, now and then, one effect on its peak.

The library comes from Freesound, CC0 only (no rights to clear, no credit to
give), the most downloaded sounds first, and is renewed every week so it follows
what people use. It needs FREESOUND_API_KEY (free, freesound.org/apiv2/apply);
without it, no sound is added.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import random
import subprocess
from typing import Any
import urllib.parse
import urllib.request

# Moods Gemini picks from, and what is searched for each; music lasts long enough to loop.
MUSIC = {
    "hype": "hip hop instrumental beat",
    "chill": "lofi beat",
    "epic": "epic orchestral",
    "sad": "sad violin",
    "funny": "funny comedy music",
    "tense": "suspense tension music",
}
EFFECTS = {
    "boom": "vine boom",
    "cheer": "crowd cheering",
    "whoosh": "whoosh",
    "scratch": "record scratch",
    "laugh": "sitcom laugh",
}
PER_KIND = 5  # sounds kept per mood or effect
REFRESH_EVERY = timedelta(days=7)
MUSIC_SECONDS = "[20 TO 300]"
EFFECT_SECONDS = "[0 TO 4]"
MUSIC_VOLUME = 0.18  # under the voices; lowered again while someone speaks
EFFECT_VOLUME = 0.8
API = "https://freesound.org/apiv2/search/text/"


def refresh_library(directory: Path, api_key: str, now: datetime | None = None) -> str | None:
    """Download the most used CC0 sounds of each kind, at most once a week.

    Sounds that left the top are deleted, so the library follows the trends.
    Returns a summary line when it was renewed.
    """
    now = now or datetime.now(timezone.utc)
    index_path = directory / "library.json"
    index = _load(index_path)
    try:
        if now - datetime.fromisoformat(index["refreshed_at"]) < REFRESH_EVERY:
            return None
    except (KeyError, TypeError, ValueError):
        pass
    library: dict[str, list[str]] = {}
    for kind, query, seconds in (
        *[(f"music_{mood}", query, MUSIC_SECONDS) for mood, query in MUSIC.items()],
        *[(f"effect_{name}", query, EFFECT_SECONDS) for name, query in EFFECTS.items()],
    ):
        params = {
            "query": query, "filter": f'license:"Creative Commons 0" duration:{seconds}',
            "sort": "downloads_desc", "fields": "id,previews", "page_size": PER_KIND, "token": api_key,
        }
        request = urllib.request.Request(f"{API}?{urllib.parse.urlencode(params)}", headers={"User-Agent": "automatiseur"})
        with urllib.request.urlopen(request, timeout=30) as response:
            results = json.load(response).get("results") or []
        folder = directory / kind
        folder.mkdir(parents=True, exist_ok=True)
        kept = []
        for result in results:
            path = folder / f"{result['id']}.mp3"
            if not path.exists():
                with urllib.request.urlopen(result["previews"]["preview-hq-mp3"], timeout=60) as response:
                    path.write_bytes(response.read())
            kept.append(path.name)
        for old in folder.glob("*.mp3"):
            if old.name not in kept:
                old.unlink()  # no longer among the most used
        library[kind] = kept
    index_path.write_text(json.dumps({"refreshed_at": now.isoformat(), "library": library}), encoding="utf-8")
    return f"Sons renouveles : {sum(map(len, library.values()))} (musiques et effets libres de droits)."


def pick(directory: Path, kind: str) -> Path | None:
    """A random sound of ``kind`` ("music_hype", "effect_boom"...), or None."""
    names = (_load(directory / "library.json").get("library") or {}).get(kind) or []
    paths = [directory / kind / name for name in names if (directory / kind / name).exists()]
    return random.choice(paths) if paths else None


def mix_command(
    short: Path, output: Path, music: Path | None, effect: Path | None, effect_at: float | None,
) -> list[str]:
    """FFmpeg command adding the music (looped, lowered while someone speaks) and the effect
    (at ``effect_at`` seconds) to a rendered Short; the picture is copied as is."""
    inputs, graph, mixed = ["-i", str(short)], [], ["[0:a]"]
    if music is not None:
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        graph += [
            f"[1:a]volume={MUSIC_VOLUME}[m]",
            "[0:a]asplit[voice][key]",
            "[m][key]sidechaincompress=threshold=0.02:ratio=6:attack=20:release=400[bed]",
        ]
        mixed = ["[voice]", "[bed]"]
    if effect is not None and effect_at is not None:
        inputs += ["-i", str(effect)]
        delay = max(0, round(effect_at * 1000))
        graph.append(f"[{2 if music is not None else 1}:a]adelay={delay}|{delay},volume={EFFECT_VOLUME}[fx]")
        mixed.append("[fx]")
    graph.append(f"{''.join(mixed)}amix=inputs={len(mixed)}:duration=first:normalize=0[a]")
    return [
        "ffmpeg", "-y", *inputs, "-filter_complex", ";".join(graph),
        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", str(output),
    ]


def add_sounds(short: Path, music: Path | None, effect: Path | None, effect_at: float | None) -> bool:
    """Mix the sounds into ``short`` in place; False (Short unchanged) if FFmpeg fails."""
    if music is None and (effect is None or effect_at is None):
        return False
    temporary = short.with_name(f"{short.stem}.sound.mp4")
    try:
        subprocess.run(mix_command(short, temporary, music, effect, effect_at),
                       stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=300)
        temporary.replace(short)
        return True
    except (OSError, subprocess.SubprocessError):
        temporary.unlink(missing_ok=True)
        return False


def _load(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}
