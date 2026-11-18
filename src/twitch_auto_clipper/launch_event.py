"""GTA 6 launch week (owner, 2026-11-18): GTA 6 streams first, until ``END``.

Every boost of the app goes through ``boosted``: once ``END`` is past it is always
False and the app behaves exactly as before the launch week (git tag
``before-gta6-launch``). Nothing else needs to be undone.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re

END = datetime(2026, 11, 26, tzinfo=timezone.utc)  # launch on 11-19, seven days
MIN_VIEWERS = 1000  # GTA 6 streams followed from this many viewers (5000 for the others)
CLIP_BUDGET = 5  # their budget below 5000 viewers (the acquisition then asks for the top-list 25)
TITLE_TAG = " (GTA 6)"
HASHTAGS = "#gta6 #gtavi "

# "Grand Theft Auto VI", "GTA 6"... never "Grand Theft Auto: Vice City" or "GTA V".
_GTA6 = re.compile(r"\b(grand theft auto|gta)\s*(vi|6)\b", re.IGNORECASE)


def active(now: datetime | None = None) -> bool:
    return (now or datetime.now(timezone.utc)) < END


def also_for_irl(record: dict, game_name: str | None, now: datetime | None = None) -> bool:
    """A GTA 6 Short of the gaming channel showing mostly the streamer: PeakMoments may publish it too.

    LiveActions! gets far more GTA 6 Shorts than it can publish that week; the ones about the
    streamer's reaction rather than the game suit PeakMoments best (they compete there on score).
    """
    return (record.get("channel") or "gaming") == "gaming" and bool(record.get("on_webcam")) and boosted(game_name, now)


def boosted(game_name: str | None, now: datetime | None = None) -> bool:
    """True for a GTA 6 stream during the launch week."""
    return active(now) and bool(_GTA6.search(game_name or ""))
