"""A/B tests of how the Shorts are made, one channel at a time.

``config/experiments.json`` lists the running tests: each one changes a few settings for
half of a channel's VODs (variant "B", drawn from the VOD id, so the same VOD always gets
the same variant) while the other half keeps the current way ("A"). Both halves are
published over the same days, so their results compare cleanly. Every Short records its
variants; the daily optimization loop reads the results and keeps the winner.

Settings a test can change (variant "B" only):
- ``selection_rules``: rules added to Gemini's moment selection (moment, hook, title);
- ``trim_rules`` and ``ideal_seconds``: rules and target length for each Short's bounds;
- ``cold_open``: false turns the cold open off.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

CONFIG = Path(__file__).resolve().parents[2] / "config" / "experiments.json"


def running(channel: str, path: Path = CONFIG) -> list[dict[str, Any]]:
    try:
        tests = json.loads(path.read_text(encoding="utf-8")).get("experiments", [])
    except (OSError, json.JSONDecodeError, AttributeError):
        return []
    return [test for test in tests if isinstance(test, dict) and test.get("channel") == channel and test.get("id")]


def variant(test_id: str, vod_id: str) -> str:
    return "B" if int(hashlib.sha1(f"{test_id}:{vod_id}".encode()).hexdigest(), 16) % 2 else "A"


def for_vod(vod_id: str, channel: str, path: Path = CONFIG) -> tuple[dict[str, str], dict[str, Any]]:
    """This VOD's variant in each running test of the channel, and the settings of its "B" tests."""
    variants, settings = {}, {}
    for test in running(channel, path):
        variants[test["id"]] = variant(test["id"], vod_id)
        if variants[test["id"]] == "B":
            for key, value in (test.get("b") or {}).items():
                if isinstance(value, list) and isinstance(settings.get(key), list):
                    settings[key] = settings[key] + value
                else:
                    settings[key] = value
    return variants, settings


def rules_text(rules: list[str]) -> str:
    return "Regles a appliquer en plus :\n" + "\n".join(f"- {rule}" for rule in rules) if rules else ""
