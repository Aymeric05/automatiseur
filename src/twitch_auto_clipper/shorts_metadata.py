"""Title and description for a generated Short, built from its real content."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

TITLE_MAX_LENGTH = 100  # YouTube limit
DESCRIPTION_MAX_LENGTH = 5000  # YouTube limit
QUOTE_MAX_WORDS = 12
TITLE_MIN_QUOTE_WORDS = 6
EXCERPT_MAX_LENGTH = 400


class ShortMetadataError(ValueError):
    """Raised when no truthful metadata can be built for a Short."""


@dataclass(frozen=True)
class ShortMetadata:
    title: str
    description: str


def _clean(text: str) -> str:
    # YouTube rejects "<" and ">" in titles and descriptions.
    text = text.replace("<", "").replace(">", "")
    return re.sub(r"\s+", " ", text).strip()


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:.-")
    return f"{cut}…"


def clip_transcript_text(
    segments: list[dict[str, Any]], start: float, end: float
) -> str:
    """Return the words actually spoken between start and end.

    Segments that are mostly outside the interval (e.g. the tail of the previous
    sentence caught by the clip margin) are skipped so the text starts cleanly.
    """
    words: list[str] = []
    for segment in segments:
        try:
            segment_start = float(segment.get("start", 0))
            segment_end = float(segment.get("end", 0))
        except (TypeError, ValueError):
            continue
        if segment_end <= start or segment_start >= end:
            continue
        overlap = min(end, segment_end) - max(start, segment_start)
        if segment_end > segment_start and overlap < 0.5 * (segment_end - segment_start):
            continue
        segment_words = segment.get("words") or []
        timed = [
            word for word in segment_words
            if isinstance(word, dict)
            and isinstance(word.get("start"), (int, float))
            and isinstance(word.get("end"), (int, float))
        ]
        if timed:
            # Whisper words usually carry their own leading space (" $7", ",000."):
            # add a space only when a token has none and is not punctuation,
            # so "$7,000" stays intact whatever the token format.
            joined = ""
            for word in timed:
                if word["end"] > start and word["start"] < end:
                    token = str(word.get("word", ""))
                    if joined and token and not token[0].isspace() and token[0] not in ",.!?;:'%":
                        token = " " + token
                    joined += token
            words.append(joined)
        else:
            words.append(str(segment.get("text", "")))
    return _clean(" ".join(word.strip() for word in words if word.strip()))


def build_short_metadata(
    *,
    broadcaster_name: str,
    broadcaster_login: str,
    vod_id: str,
    segments: list[dict[str, Any]],
    clip_start: float,
    clip_end: float,
    candidate_start: float | None = None,
    candidate_end: float | None = None,
) -> ShortMetadata:
    """Build a title and description only from the clip's transcript and source.

    The title quotes what is said at the highlighted moment (the Gemini-selected
    candidate), and the description adds the spoken excerpt of the whole clip
    plus a credit to the Twitch channel and VOD. Nothing is invented.
    """
    name = _clean(broadcaster_name) or _clean(broadcaster_login)
    if not name:
        raise ShortMetadataError("Nom de la chaine Twitch manquant.")

    highlight_start = candidate_start if candidate_start is not None else clip_start
    highlight_end = candidate_end if candidate_end is not None else clip_end
    quote = clip_transcript_text(segments, highlight_start, highlight_end)
    excerpt = clip_transcript_text(segments, clip_start, clip_end)
    if len(quote.split()) < TITLE_MIN_QUOTE_WORDS and excerpt:
        # A bare reaction ("Oh my god.") says little: quote the clip's most
        # substantial sentence instead.
        quote = max(re.split(r"(?<=[.!?])\s+", excerpt), key=lambda s: len(s.split()))
    if not quote:
        raise ShortMetadataError("Aucun texte transcrit pour ce clip.")

    quote_words = quote.split()
    short_quote = " ".join(quote_words[:QUOTE_MAX_WORDS])
    if len(quote_words) > QUOTE_MAX_WORDS:
        short_quote += "…"
    title = _truncate(f"{name}: “{short_quote}”", TITLE_MAX_LENGTH)

    lines = [f"“{_truncate(excerpt or quote, EXCERPT_MAX_LENGTH)}”", ""]
    lines.append(f"Clip from {name}'s Twitch stream.")
    if broadcaster_login:
        lines.append(f"Channel: https://www.twitch.tv/{_clean(broadcaster_login)}")
    lines.append(f"Original VOD: https://www.twitch.tv/videos/{_clean(vod_id)}")
    lines.extend(["", "#Shorts #Twitch"])
    description = _truncate("\n".join(lines), DESCRIPTION_MAX_LENGTH)
    return ShortMetadata(title=title, description=description)
