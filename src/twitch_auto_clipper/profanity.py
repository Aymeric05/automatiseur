"""Swear words: muted in a Short's audio and masked in its text; slurs: moment dropped."""

from __future__ import annotations

import re
from typing import Any

# ponytail: word lists, not a classifier; add a word here when one slips through.
_SWEARS = (
    r"f+u+c+k\w*|motherf\w*|f\*+\w*|sh[i1]t\w*|s\*+t|bullshit\w*|b[i1]tch\w*|bastards?"
    r"|assholes?|dumbass\w*|jackass\w*|dick(?:s|head\w*)?|cocks?|cocksucker\w*|puss(?:y|ies)"
    r"|cunts?|whores?|sluts?|twats?|wankers?|pricks?|piss(?:ed|ing)?"
)
_SLURS = r"n[i1]gg(?:a|er|uh)s?|f[a4]g(?:g[o0]t)?s?|retard(?:ed|s)?|trann(?:y|ies)"
# Lookarounds instead of \b, so that Whisper's own "f***ing" is caught too.
PROFANITY = re.compile(rf"(?<![\w*])(?:{_SWEARS}|{_SLURS})(?![\w*])", re.IGNORECASE)
SLURS = re.compile(rf"(?<![\w*])(?:{_SLURS})(?![\w*])", re.IGNORECASE)
MUTE_PADDING = 0.15  # seconds muted around a word: Whisper's word times are approximate


def censor(text: str) -> str:
    """Replace every swear word by as many asterisks."""
    return PROFANITY.sub(lambda match: "*" * len(match.group()), text)


def has_slur(text: str) -> bool:
    return bool(SLURS.search(text))


def profane_intervals(
    segments: list[dict[str, Any]] | None, start: float, end: float
) -> list[tuple[float, float]]:
    """When swear words are said between start and end, in seconds from start."""
    intervals = []
    for segment in segments or []:
        for word in segment.get("words") or []:
            try:
                word_start, word_end = float(word["start"]), float(word["end"])
                text = str(word["word"]).strip(" .,!?;:'\"")
            except (KeyError, TypeError, ValueError):
                continue
            if word_end > start and word_start < end and PROFANITY.fullmatch(text):
                intervals.append((
                    round(max(0.0, word_start - start - MUTE_PADDING), 2),
                    round(min(end, word_end) - start + MUTE_PADDING, 2),
                ))
    return intervals
