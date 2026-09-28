"""Chat activity analysis helpers."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
import sys
from typing import Any


class ChatActivityError(RuntimeError):
    """Raised when Twitch chat data cannot be read."""


def load_chat_messages(input_path: Path) -> list[dict[str, Any]]:
    """Load timestamped messages from TwitchDownloaderCLI JSON output."""
    try:
        data = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ChatActivityError(f"Impossible de lire le chat : {input_path}") from error

    if isinstance(data, dict):
        messages = data.get("comments", [])
    else:
        messages = data
    if not isinstance(messages, list):
        raise ChatActivityError("Le fichier chat doit contenir une liste de messages.")

    normalized: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        if "content_offset_seconds" not in message and "timestamp" in message:
            # Already normalized (the pipeline's *_chat_timestamps.json).
            message = {**message.get("message", {}), "content_offset_seconds": message["timestamp"]}
        try:
            timestamp = float(message["content_offset_seconds"])
        except (KeyError, TypeError, ValueError):
            continue
        normalized.append({"timestamp": timestamp, "message": message})
    return normalized


def count_messages_in_window(
    messages: list[dict[str, Any]], timestamp: float, window_seconds: float = 30.0
) -> int:
    """Count chat messages around a timestamp."""
    if window_seconds < 0:
        raise ValueError("La fenetre du chat doit etre positive ou nulle.")
    return sum(
        1
        for message in messages
        if abs(float(message["timestamp"]) - timestamp) <= window_seconds
    )


def add_chat_activity(
    candidates: list[dict[str, float]],
    messages: list[dict[str, Any]],
    window_seconds: float = 30.0,
) -> list[dict[str, float | int]]:
    """Add an explainable chat message count to highlight candidates."""
    return [
        {
            **candidate,
            "chat_messages": count_messages_in_window(
                messages, candidate["start"], window_seconds
            ),
        }
        for candidate in candidates
    ]


def _message_text(message: dict[str, Any]) -> str:
    payload = message.get("message", message)
    if not isinstance(payload, dict):
        return str(payload).strip()
    if isinstance(payload.get("message"), dict):
        # Real TwitchDownloaderCLI comment: the text lives in comment["message"]["body"].
        payload = payload["message"]
    if payload.get("body"):
        return str(payload["body"]).strip()
    fragments = payload.get("fragments")
    if isinstance(fragments, list):
        return "".join(
            str(fragment.get("text", ""))
            for fragment in fragments
            if isinstance(fragment, dict)
        ).strip()
    return ""


def add_chat_messages(
    candidates: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    window_seconds: float = 30.0,
) -> list[dict[str, Any]]:
    """Attach timestamped chat messages to each candidate's time window."""
    if window_seconds < 0:
        raise ValueError("La fenetre du chat doit etre positive ou nulle.")
    enriched: list[dict[str, Any]] = []
    for candidate in candidates:
        start = float(candidate["start"])
        end = float(candidate["end"])
        matching_messages = [
            {
                "timestamp": float(message["timestamp"]),
                "text": _message_text(message),
            }
            for message in messages
            if start - window_seconds
            <= float(message["timestamp"])
            <= end + window_seconds
        ]
        enriched.append(
            {
                **candidate,
                "chat_messages": len(matching_messages),
                "chat_message_details": matching_messages,
            }
        )
    return enriched


# Chat reacts 1-3 s after a line and keeps reacting ~10 s (measured by hand on
# one VOD, not calibrated): the window is shifted by these amounts.
CHAT_LAG_START_SECONDS = 2.0
CHAT_LAG_END_SECONDS = 8.0
LOCAL_BASELINE_SECONDS = 120.0  # activity is compared to the surrounding minutes
# Stream start is mostly greetings and hype: the signal is flagged unreliable there.
STREAM_START_UNRELIABLE_SECONDS = 240.0
LAUGH_TEXT = re.compile(r"\b(lol+|lmf?ao+|kek\w*|lul\w*|ha(ha)+h?|icant|xd+)\b|😂|🤣|💀", re.I)
LAUGH_EMOTE = re.compile(r"kek|lul|laugh", re.I)
GREETING_WORDS = re.compile(
    r"^(h+i+)+[!.,]*$|^(hey+|hello+|hiya|hai+|halo)[!.,]*$|^(yo+|sup|gm)$", re.I
)
GREETING_OPENERS = re.compile(r"^((h+i+)+|hey+|hello+|hiya|hai+|halo)[!.,]*$", re.I)
GREETING_PHRASE = re.compile(r"^good (morning|afternoon|evening|night)\b", re.I)
GREETING_EMOTE = re.compile(r"Hi(?![a-z])|[Ww]av(e|ing)")
# Generic reactions only: channel-specific codes are reported by top_reactions.
SHORT_REACTIONS = re.compile(r"^(o+|w+|l+|oh+|omg+|wow+|pog\w*|what+|wtf+|no+|yes+|\?+|!+)$", re.I)
# Twitch notices echoed in the chat replay (subs, gifts, watch streaks).
SYSTEM_MESSAGE = re.compile(
    r"^\S+ (subscribed (at|with)|is gifting|gifted (a|an|\d+)|converted from|is continuing the gift"
    r"|is paying forward|watched \d+ consecutive streams)",
    re.I,
)
MAX_SAMPLE_MESSAGES = 5
MAX_SAMPLE_CHARACTERS = 120


def _emotes(message: dict[str, Any]) -> list[str]:
    payload = message.get("message", message)
    payload = payload.get("message", payload) if isinstance(payload, dict) else {}
    fragments = payload.get("fragments") if isinstance(payload, dict) else None
    return [
        str(fragment.get("text", ""))
        for fragment in fragments or []
        if isinstance(fragment, dict) and fragment.get("emoticon")
    ]


def _author(message: dict[str, Any]) -> str | None:
    payload = message.get("message", message)
    commenter = payload.get("commenter") if isinstance(payload, dict) else None
    if isinstance(commenter, dict):
        return commenter.get("_id") or commenter.get("name")
    return None


def _is_greeting(text: str, emotes: list[str]) -> bool:
    tokens = text.split()
    if not tokens:
        return False
    if all(
        GREETING_WORDS.match(token) or (token in emotes and GREETING_EMOTE.search(token))
        for token in tokens
    ):
        return True
    # "hi rae", "hiii rae and chat", "good morning everyone": short and opened by a greeting.
    return (GREETING_OPENERS.match(tokens[0]) and len(tokens) <= 4) or bool(
        GREETING_PHRASE.match(text) and len(tokens) <= 5
    )


def _is_laugh(text: str, emotes: list[str]) -> bool:
    return bool(LAUGH_TEXT.search(text)) or any(LAUGH_EMOTE.search(e) for e in emotes)


def _is_noise(text: str, emotes: list[str]) -> bool:
    """Greetings, Twitch notices and emote spam say nothing about the moment."""
    tokens = text.split()
    emote_only = bool(tokens) and all(token in emotes for token in tokens)
    return (
        _is_greeting(text, emotes)
        or bool(SYSTEM_MESSAGE.match(text))
        or (emote_only and not _is_laugh(text, emotes))  # laugh emotes are reactions
    )


def chat_signal(
    messages: list[dict[str, Any]],
    start: float,
    end: float,
    lag_start: float = CHAT_LAG_START_SECONDS,
    lag_end: float = CHAT_LAG_END_SECONDS,
    baseline_seconds: float = LOCAL_BASELINE_SECONDS,
    vod_end: float | None = None,
) -> dict[str, Any]:
    """Describe chat reactions to [start, end], seen in [start + lag_start, end + lag_end].

    Greetings, Twitch notices and non-laugh emote spam are left out.
    ``activity_ratio`` compares the window's message rate to the rate of the
    surrounding ``baseline_seconds`` on each side, cut at the VOD bounds
    (``vod_end`` defaults to the last chat message); it is None when the
    surroundings are silent. ``reliable`` is False at stream start or without
    a baseline: the signal is context for Gemini, never a filter.
    """
    window_start, window_end = start + lag_start, end + lag_end
    if vod_end is None:
        vod_end = max((float(m["timestamp"]) for m in messages), default=window_end)
    inside, around = [], 0
    for message in messages:
        timestamp = float(message["timestamp"])
        if timestamp < window_start - baseline_seconds or timestamp > window_end + baseline_seconds:
            continue
        text, emotes = _message_text(message), _emotes(message)
        if _is_noise(text, emotes):
            continue
        if window_start <= timestamp <= window_end:
            inside.append((text, emotes, _author(message)))
        else:
            around += 1

    duration = max(min(window_end, vod_end) - window_start, 1.0)
    around_duration = (window_start - max(0.0, window_start - baseline_seconds)) + max(
        0.0, min(vod_end, window_end + baseline_seconds) - window_end
    )
    baseline_rate = around / around_duration if around_duration > 0 else 0.0
    count = len(inside)
    laughs = sum(_is_laugh(text, emotes) for text, emotes, _ in inside)
    short = sum(bool(SHORT_REACTIONS.match(text.strip())) for text, _, _ in inside)
    # Repeated short messages, whatever the channel's own codes are ("om", "W", "KEKW").
    reactions = Counter(
        text.strip().lower()
        for text, _, _ in inside
        if 0 < len(text.split()) <= 2 and len(text.strip()) <= 15
    )
    samples = list(dict.fromkeys(
        text.strip()[:MAX_SAMPLE_CHARACTERS] for text, _, _ in inside if len(text.split()) >= 3
    ))
    return {
        "messages": count,
        "rate": round(count / duration, 2),
        "activity_ratio": round((count / duration) / baseline_rate, 2) if baseline_rate else None,
        "distinct_authors": len({author for _, _, author in inside if author}),
        "laugh_ratio": round(laughs / count, 2) if count else 0.0,
        "short_reaction_ratio": round(short / count, 2) if count else 0.0,
        "top_reactions": [[text, n] for text, n in reactions.most_common(3) if n >= 2],
        "sample_messages": samples[:: max(1, len(samples) // MAX_SAMPLE_MESSAGES)][:MAX_SAMPLE_MESSAGES],
        "reliable": window_start >= STREAM_START_UNRELIABLE_SECONDS and baseline_rate > 0,
    }


def add_chat_signals(
    candidates: list[dict[str, Any]], messages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Attach a ``chat_signal`` summary to each candidate (context for Gemini, not a score)."""
    vod_end = max((float(m["timestamp"]) for m in messages), default=None)
    return [
        {
            **candidate,
            "chat_signal": chat_signal(
                messages, float(candidate["start"]), float(candidate["end"]), vod_end=vod_end
            ),
        }
        for candidate in candidates
    ]


def save_chat_activity(
    candidates: list[dict[str, float | int]], output_path: Path
) -> None:
    """Save candidates enriched with chat activity as JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    """Print the chat signal of saved candidates (offline: no download, no Gemini).

    Usage: python -m twitch_auto_clipper.chat_activity <chat.json> <highlights.json>
    """
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print(main.__doc__.strip().splitlines()[-1].strip(), file=sys.stderr)
        return 2
    messages = load_chat_messages(Path(argv[0]))
    candidates = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    print(
        f"{len(messages)} messages, {len(candidates)} candidats "
        f"(fenetre chat +{CHAT_LAG_START_SECONDS:g}s / +{CHAT_LAG_END_SECONDS:g}s)"
    )
    print("candidat        debut-fin       msg  x_local  auteurs  rires  reactions  fiable  reactions repetees")
    for index, candidate in enumerate(add_chat_signals(candidates, messages), start=1):
        s = candidate["chat_signal"]
        ratio = "-" if s["activity_ratio"] is None else f"{s['activity_ratio']:.2f}"
        top = " ".join(f"{text}x{n}" for text, n in s["top_reactions"])
        print(
            f"candidate_{index:<4} {candidate['start']:7.1f}-{candidate['end']:7.1f}s {s['messages']:5d}"
            f"  {ratio:>7}  {s['distinct_authors']:7d}  {s['laugh_ratio']:5.0%}  {s['short_reaction_ratio']:8.0%}"
            f"  {'oui' if s['reliable'] else 'non':>6}  {top}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
