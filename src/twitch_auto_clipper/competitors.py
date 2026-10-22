"""What the big YouTube channels that clip Twitch streams teach the app.

Each week, the app looks for big channels (at least ``MIN_SUBSCRIBERS``) that post Shorts of
Twitch streams, one set per theme (video games for LiveActions!, IRL / Just Chatting for
PeakMoments), keeping only those whose recent Shorts are mostly about known streamers. Each
day, it reads their Shorts published 2 to 60 days ago: views, likes, comments, length, title
and streamer (public data; the share watched is private to each channel). Each Short is
compared with its own channel's usual views, so a huge channel does not drown the others.

The ranking then learns small, fading points from them (see performance.external_points),
and Gemini sees the titles that do best and worst on those channels.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from typing import Any, Callable

COMPETITORS_FILE = "competitor_shorts.json"
QUERIES = {
    "gaming": ["twitch clips gaming shorts", "twitch streamer funny moments shorts", "twitch gaming clips"],
    "irl": ["twitch irl clips shorts", "just chatting clips shorts", "kai cenat clips shorts"],
}
MIN_SUBSCRIBERS = 50_000
SEARCHED_STREAMERS = 5  # "<streamer> clips" searched for the first ones of each theme's list
MAX_CHANNELS = 10  # per theme, the biggest relevant ones
MIN_RELEVANT_SHARE = 0.3  # of a channel's recent Shorts about a streamer of the theme's list
DISCOVERY_INTERVAL = timedelta(days=7)
REFRESH_INTERVAL = timedelta(hours=24)
MIN_AGE = timedelta(days=2)  # younger Shorts' views are not settled
MAX_AGE = timedelta(days=60)
MAX_SHORT_SECONDS = 180


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def find_streamer(text: str, logins: list[str]) -> str | None:
    """The known streamer a Short is about: their login in its title, tags or description."""
    squashed, words = _squash(text), set(re.findall(r"[a-z0-9_]+", text.lower()))
    for login in sorted(logins, key=len, reverse=True):  # "kaicenat" before "kai"
        if (len(login) >= 5 and _squash(login) in squashed) or login in words:
            return login
    return None


def _seconds(duration: str) -> int:
    match = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration or "")
    if not match:
        return 0
    days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return ((days * 24 + hours) * 60 + minutes) * 60 + seconds


def _recent_shorts(service: Any, channel_id: str, logins: list[str], now: datetime) -> list[dict[str, Any]]:
    channel = service.channels().list(part="contentDetails", id=channel_id).execute(num_retries=3)["items"][0]
    playlist = channel["contentDetails"]["relatedPlaylists"]["uploads"]
    items = service.playlistItems().list(part="contentDetails", playlistId=playlist, maxResults=50).execute(num_retries=3)
    ids = [item["contentDetails"]["videoId"] for item in items.get("items", [])]
    if not ids:
        return []
    videos = service.videos().list(part="snippet,contentDetails,statistics", id=",".join(ids)).execute(num_retries=3)
    shorts = []
    for video in videos.get("items", []):
        seconds = _seconds(video["contentDetails"].get("duration", ""))
        published = datetime.fromisoformat(video["snippet"]["publishedAt"].replace("Z", "+00:00"))
        if not 0 < seconds <= MAX_SHORT_SECONDS or not MIN_AGE <= now - published <= MAX_AGE:
            continue
        snippet, stats = video["snippet"], video.get("statistics", {})
        text = " ".join([snippet.get("title", ""), " ".join(snippet.get("tags", [])), snippet.get("description", "")[:300]])
        shorts.append({
            "video_id": video["id"], "channel_id": channel_id, "title": snippet.get("title", ""),
            "views": int(stats.get("viewCount", 0)), "likes": int(stats.get("likeCount", 0)),
            "comments": int(stats.get("commentCount", 0)), "seconds": seconds,
            "published": published.isoformat(timespec="seconds"), "streamer": find_streamer(text, logins),
        })
    return shorts


def _discover(service: Any, theme: str, theme_logins: list[str], logins: list[str], now: datetime) -> list[str]:
    """The biggest channels whose recent Shorts are mostly about this theme's streamers."""
    found: list[str] = []
    for query in QUERIES[theme] + [f"{login} clips" for login in theme_logins[:SEARCHED_STREAMERS]]:
        result = service.search().list(
            part="snippet", q=query, type="channel", maxResults=25, relevanceLanguage="en"
        ).execute(num_retries=3)
        found += [item["snippet"]["channelId"] for item in result.get("items", [])]
    found = list(dict.fromkeys(found))
    channels = []
    for index in range(0, len(found), 50):  # every channel found, 50 per request
        channels += service.channels().list(
            part="statistics", id=",".join(found[index:index + 50])
        ).execute(num_retries=3).get("items", [])
    big = sorted(
        (c for c in channels if int(c.get("statistics", {}).get("subscriberCount", 0)) >= MIN_SUBSCRIBERS),
        key=lambda c: -int(c["statistics"]["subscriberCount"]),
    )
    relevant = []
    for channel in big:
        shorts = _recent_shorts(service, channel["id"], logins, now)
        on_theme = sum(s["streamer"] in theme_logins for s in shorts)
        if len(shorts) >= 10 and on_theme / len(shorts) >= MIN_RELEVANT_SHARE:
            relevant.append(channel["id"])
        if len(relevant) >= MAX_CHANNELS:
            break
    return relevant


def refresh_competitors(
    output_dir: Path,
    service_factory: Callable[[], Any],
    theme_logins: dict[str, list[str]],
    clock: Callable[[], datetime] | None = None,
) -> str | None:
    """Once a day, read the Shorts of the big clip channels (found again once a week).

    ``theme_logins``: each theme's streamers list, in order (a channel belongs to the
    theme whose streamers its Shorts are about).
    """
    logins = sorted({login for values in theme_logins.values() for login in values})
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    path = output_dir / COMPETITORS_FILE
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        state = {}
    try:
        if now - datetime.fromisoformat(state["refreshed_at"]) < REFRESH_INTERVAL:
            return None
    except (KeyError, TypeError, ValueError):
        pass
    service = service_factory()
    channels = state.get("channels") or {}
    try:
        discovery_due = now - datetime.fromisoformat(state["discovered_at"]) >= DISCOVERY_INTERVAL
    except (KeyError, TypeError, ValueError):
        discovery_due = True
    if discovery_due:
        channels = {theme: _discover(service, theme, theme_logins[theme], logins, now) for theme in QUERIES}
        # A channel found for both themes stays in the one most of its Shorts are about.
        shared = set(channels["gaming"]) & set(channels["irl"])
        for channel_id in shared:
            shorts = _recent_shorts(service, channel_id, logins, now)
            gaming = sum(s["streamer"] in theme_logins["gaming"] for s in shorts)
            mostly_irl = gaming * 2 < len([s for s in shorts if s["streamer"]])
            channels["gaming" if mostly_irl else "irl"].remove(channel_id)
        state["discovered_at"] = now.isoformat(timespec="seconds")
    shorts = []
    for theme, ids in channels.items():
        for channel_id in ids:
            try:
                shorts += [{**short, "theme": theme} for short in _recent_shorts(service, channel_id, logins, now)]
            except Exception:
                continue  # one channel unavailable: the others still count
    state.update({"channels": channels, "refreshed_at": now.isoformat(timespec="seconds"), "shorts": shorts})
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    counts = {theme: sum(s["theme"] == theme for s in shorts) for theme in channels}
    return "Chaines de clips analysees : " + ", ".join(
        f"{theme} {len(channels[theme])} chaines / {counts[theme]} Shorts" for theme in channels
    )


def load_competitor_shorts(output_dir: Path) -> list[dict[str, Any]]:
    try:
        return json.loads((output_dir / COMPETITORS_FILE).read_text(encoding="utf-8")).get("shorts", [])
    except (OSError, json.JSONDecodeError, AttributeError):
        return []


GUIDE_FILE = "format_guide.json"
STUDY_INTERVAL = timedelta(days=7)
STUDIED_SHORTS = 8  # best and worst of each theme, watched by Gemini
GUIDE_SCHEMA = {
    "type": "object",
    "properties": {
        "rules": {"type": "array", "items": {"type": "string"}},
        "ideal_seconds": {"type": "array", "items": {"type": "number"}},
    },
    "required": ["rules", "ideal_seconds"],
}


def study_formats(
    output_dir: Path,
    generate: Callable[..., tuple[str, str]],
    clock: Callable[[], datetime] | None = None,
) -> str | None:
    """Once a week, Gemini watches the best and worst Shorts of each theme's big clip channels
    and writes how a Short that works is made (``format_guide.json``).

    ``generate(contents, schema)`` asks Gemini for JSON (contents: text and video links).
    """
    import math
    import statistics

    from google.genai import types

    now = (clock or (lambda: datetime.now(timezone.utc)))()
    path = output_dir / GUIDE_FILE
    try:
        guide = json.loads(path.read_text(encoding="utf-8"))
        if now - datetime.fromisoformat(guide["studied_at"]) < STUDY_INTERVAL:
            return None
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        guide = {}
    shorts = load_competitor_shorts(output_dir)
    studied = {}
    for theme in QUERIES:
        own = [short for short in shorts if short.get("theme") == theme]
        logs: dict[str, list[float]] = {}
        for short in own:
            logs.setdefault(short["channel_id"], []).append(math.log10(short["views"] + 1))
        medians = {channel: statistics.median(values) for channel, values in logs.items()}
        ranked = sorted(own, key=lambda short: math.log10(short["views"] + 1) - medians[short["channel_id"]])
        if len(ranked) < 2 * STUDIED_SHORTS:
            continue
        best, worst = ranked[-STUDIED_SHORTS:][::-1], ranked[:STUDIED_SHORTS]
        contents: list[Any] = [
            "Voici des YouTube Shorts de grosses chaines qui reprennent des lives Twitch "
            + ("de jeux video. " if theme == "gaming" else "IRL / Just Chatting. ")
            + f"Les {STUDIED_SHORTS} premiers sont ceux qui ont le MIEUX marche (par rapport a leur "
            f"chaine), les {STUDIED_SHORTS} suivants ceux qui ont le MOINS bien marche. Regarde-les et "
            "compare comment ils sont faits : les premieres secondes, le contexte donne, la fin, la "
            "duree, le type de moment, le texte a l'ecran (accroche, sous-titres), le titre. Ecris 6 "
            "a 10 regles courtes et concretes pour faire des Shorts qui marchent, utilisables pour "
            "choisir le moment d'un live, ou le commencer et le finir, et ecrire l'accroche et le "
            "titre (pas de regle sur le montage, la musique ou les effets, ni sur un streamer "
            "precis). ideal_seconds : [duree min, duree max] des Shorts qui marchent le mieux. "
            'Retourne un JSON {"rules":["..."],"ideal_seconds":[15,30]}.'
        ]
        for label, group in (("MIEUX", best), ("MOINS BIEN", worst)):
            for short in group:
                contents += [
                    f"{label} - {short['title']} ({short['seconds']} s, {short['views']} vues) :",
                    types.Part.from_uri(file_uri=f"https://www.youtube.com/watch?v={short['video_id']}", mime_type="video/*"),
                ]
        try:
            answer = json.loads(generate(contents, GUIDE_SCHEMA)[0])
            low, high = (float(value) for value in answer["ideal_seconds"][:2])
            studied[theme] = {
                "rules": [str(rule).strip() for rule in answer["rules"] if str(rule).strip()][:10],
                "ideal_seconds": [max(15.0, min(low, high)), min(58.0, max(low, high))],
            }
        except Exception:
            continue  # this theme keeps its previous guide
    if not studied:
        return None
    guide.update(studied)
    guide["studied_at"] = now.isoformat(timespec="seconds")
    path.write_text(json.dumps(guide, ensure_ascii=False, indent=1), encoding="utf-8")
    return "Guide de fabrication mis a jour d'apres les grosses chaines : " + ", ".join(
        f"{theme} ({len(value['rules'])} regles, {value['ideal_seconds'][0]:.0f}-{value['ideal_seconds'][1]:.0f} s)"
        for theme, value in studied.items()
    )


def format_guide(output_dir: Path, theme: str) -> dict[str, Any]:
    """This theme's guide: ``rules`` and ``ideal_seconds`` (empty before the first study)."""
    try:
        guide = json.loads((output_dir / GUIDE_FILE).read_text(encoding="utf-8")).get(theme)
    except (OSError, json.JSONDecodeError, AttributeError):
        return {}
    return guide if isinstance(guide, dict) else {}


def format_guide_text(output_dir: Path, theme: str) -> str:
    guide = format_guide(output_dir, theme)
    if not guide.get("rules"):
        return ""
    return "Comment sont faits les Shorts qui marchent sur les grosses chaines de clips :\n" + "\n".join(
        f"- {rule}" for rule in guide["rules"]
    )
