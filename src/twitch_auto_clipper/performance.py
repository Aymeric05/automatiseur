"""What the real results of the published Shorts teach the ranking of the next ones.

Each published Short gets a performance score from what viewers actually did:
views, share watched (retention), likes and comments, compared with the other
Shorts of its channel. Each feature of a Short (streamer, kind of moment,
emotion, length, cold open, Twitch category) earns or loses a few ranking
points from the performance of the Shorts that had it:

- pulled towards zero when few Shorts are measured (results are partly luck);
- recent Shorts weigh more (YouTube's algorithm and the audience change);
- self-checked: each publication records the points predicted at that time;
  once its results are known, the prediction is compared with them, and the
  learned points weigh more when they predicted well, less (down to nothing)
  when they did not. Every ranking uses the latest data: it keeps adapting.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import math
import statistics
from pathlib import Path
from typing import Any

# Shorts' results are partly luck: everything here moves slowly, over many Shorts.
HALF_LIFE_DAYS = 45.0  # a Short published 45 days ago still weighs half
MIN_AGE = timedelta(days=1)  # younger Shorts' results say nothing yet
MIN_SHORTS_PER_VALUE = 5  # a feature value seen on fewer measured Shorts earns nothing
PRIOR_WEIGHT = 10.0  # a feature's mean counts for w / (w + 10): 10 Shorts weigh half
POINTS_PER_SD = 4.0  # one standard deviation of performance, at full confidence
FEATURE_MAX_POINTS = 3.0  # what the Short is (length, kind of moment, emotion...)
STREAMER_MAX_POINTS = 1.0  # who streamed it weighs much less (a listed streamer: up to +3, never below 0)
TOTAL_MAX_POINTS = 8.0
RELIABILITY_MIN_SHORTS = 30  # predictions checked before the learned points are trusted more or less
RELIABILITY_WINDOW = 100
# What other big clip channels' Shorts show (see competitors.py): small points that
# fade as the channel's own measured Shorts pile up (half at EXTERNAL_FADE_SHORTS).
EXTERNAL_MIN_SHORTS = 5
EXTERNAL_PRIOR = 10.0
EXTERNAL_MAX_POINTS = {"streamer": 1.0, "length": 1.5}
EXTERNAL_FADE_SHORTS = 50
GEMINI_CHECK_MIN_SHORTS = 40  # Gemini's scores checked against the results before reweighting them
GEMINI_WEIGHT_RANGE = (0.6, 1.2)
# What the performance score is made of, and how much each part counts.
COMPONENTS = {"views": 0.45, "retention": 0.35, "engagement": 0.20}
# Below these views, the share watched and the likes are noise (2 views, 1 like...).
MIN_VIEWS_FOR_RETENTION = 50
MIN_VIEWS_FOR_ENGAGEMENT = 100


def features(short: dict[str, Any]) -> dict[str, str]:
    """The features of a Short (a history entry or a candidate) the ranking learns from."""
    seconds = float(short.get("seconds") or 0)
    return {
        "streamer": str(short.get("streamer") or "").lower(),
        "source": str(short.get("source") or "transcript"),
        "emotion": str(short.get("emotion") or "none"),
        "length": "<25s" if seconds < 25 else "25-40s" if seconds <= 40 else ">40s",
        "cold_open": "yes" if short.get("cold_open") else "no",
        "category": str(short.get("game") or "").lower(),
    }


def _views(entry: dict[str, Any]) -> int | None:
    for key in ("views_7d", "views_3d", "views_1d"):
        if isinstance(entry.get(key), (int, float)):
            return int(entry[key])
    return None


def _zscores(values: dict[str, float]) -> dict[str, float]:
    if len(values) < 2:
        return {key: 0.0 for key in values}
    mean = sum(values.values()) / len(values)
    sd = math.sqrt(sum((value - mean) ** 2 for value in values.values()) / len(values)) or 1.0
    return {key: (value - mean) / sd for key, value in values.items()}


def performance(entries: list[dict[str, Any]]) -> dict[str, float]:
    """Performance score of each measured Short (0: the channel's usual; +1: one deviation better)."""
    parts: dict[str, dict[str, float]] = {name: {} for name in COMPONENTS}
    for entry in entries:
        views = _views(entry)
        if views is None:
            continue
        video = entry["video_id"]
        parts["views"][video] = math.log10(views + 1)
        if isinstance(entry.get("retention_pct"), (int, float)) and views >= MIN_VIEWS_FOR_RETENTION:
            parts["retention"][video] = min(float(entry["retention_pct"]), 200.0)
        if views >= MIN_VIEWS_FOR_ENGAGEMENT:
            reactions = (entry.get("likes") or 0) + 3 * (entry.get("comments") or 0)
            parts["engagement"][video] = reactions / views
    scored = {name: _zscores(values) for name, values in parts.items()}
    # A part not measured (too few views) counts as the channel's usual (0).
    result = {
        video: sum(scored[name].get(video, 0.0) * weight for name, weight in COMPONENTS.items())
        for video in parts["views"]
    }
    mean = sum(result.values()) / len(result) if result else 0.0
    return {video: score - mean for video, score in result.items()}  # 0: the channel's usual


def _spearman(pairs: list[tuple[float, float]]) -> float:
    def ranks(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=values.__getitem__)
        result = [0.0] * len(values)
        for rank, index in enumerate(order):
            result[index] = float(rank)
        return result

    xs, ys = ranks([pair[0] for pair in pairs]), ranks([pair[1] for pair in pairs])
    mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    spread = math.sqrt(sum((x - mean_x) ** 2 for x in xs) * sum((y - mean_y) ** 2 for y in ys))
    return covariance / spread if spread else 0.0


class PerformanceModel:
    """Ranking points learned from one channel's published Shorts."""

    def __init__(
        self, history: list[dict[str, Any]], channel: str, now: datetime, protected: frozenset[str] = frozenset(),
        external: dict[tuple[str, str], float] | None = None,
    ) -> None:
        self.protected = protected  # listed streamers never lose points
        mature = [
            entry for entry in history
            if entry.get("channel", "gaming") == channel and _uploaded(entry) is not None
            and now - _uploaded(entry) >= MIN_AGE
        ]
        self.performance = performance(mature)
        # Other channels' results count less as this channel's own results pile up.
        fade = 1.0 / (1.0 + len(self.performance) / EXTERNAL_FADE_SHORTS)
        self.external = {key: points * fade for key, points in (external or {}).items()}
        sums: dict[tuple[str, str], list[float]] = {}
        counts: dict[tuple[str, str], int] = {}
        for entry in mature:
            perf = self.performance.get(entry["video_id"])
            if perf is None:
                continue
            age_days = (now - _uploaded(entry)).total_seconds() / 86400
            weight = 0.5 ** (age_days / HALF_LIFE_DAYS)
            for name, value in features(entry).items():
                if value:
                    total = sums.setdefault((name, value), [0.0, 0.0])
                    total[0] += weight * perf
                    total[1] += weight
                    counts[(name, value)] = counts.get((name, value), 0) + 1
        self.learned = {
            key: total / (weight + PRIOR_WEIGHT)
            for key, (total, weight) in sums.items() if counts[key] >= MIN_SHORTS_PER_VALUE
        }
        # Self-check: did the points predicted at publication match the real results?
        checked = [
            (float(entry["predicted_points"]), self.performance[entry["video_id"]])
            for entry in mature
            if isinstance(entry.get("predicted_points"), (int, float)) and entry["video_id"] in self.performance
        ][-RELIABILITY_WINDOW:]
        self.reliability = (
            max(0.0, min(1.5, 0.5 + 2.0 * _spearman(checked))) if len(checked) >= RELIABILITY_MIN_SHORTS else 1.0
        )
        # Gemini's score at publication against the real results: it weighs more when it
        # predicted them, less when it did not (applied around 70, the usual score).
        scored = [
            (float(entry.get("compared_score") or entry["gemini_score"]), self.performance[entry["video_id"]])
            for entry in mature
            if isinstance(entry.get("compared_score") or entry.get("gemini_score"), (int, float))
            and entry["video_id"] in self.performance
        ][-RELIABILITY_WINDOW:]
        low, high = GEMINI_WEIGHT_RANGE
        self.gemini_weight = (
            max(low, min(high, 0.8 + _spearman(scored))) if len(scored) >= GEMINI_CHECK_MIN_SHORTS else 1.0
        )

    def raw_points(self, short: dict[str, Any]) -> float:
        """Points from the features alone, before the self-check (recorded at publication)."""
        total = 0.0
        for name, value in features(short).items():
            points = POINTS_PER_SD * self.learned.get((name, value), 0.0) + self.external.get((name, value), 0.0)
            if name == "streamer" and value in self.protected:
                points = max(0.0, min(FEATURE_MAX_POINTS, points))
            elif name == "streamer":
                points = max(-STREAMER_MAX_POINTS, min(STREAMER_MAX_POINTS, points))
            total += max(-FEATURE_MAX_POINTS, min(FEATURE_MAX_POINTS, points))
        return max(-TOTAL_MAX_POINTS, min(TOTAL_MAX_POINTS, total))

    def points(self, short: dict[str, Any]) -> float:
        return self.raw_points(short) * self.reliability


def external_points(shorts: list[dict[str, Any]], theme: str) -> dict[tuple[str, str], float]:
    """Points from the big clip channels of this theme: which streamers and lengths do best.

    Each Short is compared with its own channel's median views (log scale).
    """
    by_channel: dict[str, list[float]] = {}
    for short in shorts:
        if short.get("theme") == theme:
            by_channel.setdefault(short["channel_id"], []).append(math.log10(short.get("views", 0) + 1))
    medians = {channel: statistics.median(values) for channel, values in by_channel.items()}
    sums: dict[tuple[str, str], list[float]] = {}
    for short in shorts:
        if short.get("theme") != theme:
            continue
        relative = math.log10(short.get("views", 0) + 1) - medians[short["channel_id"]]
        for key in (("streamer", short.get("streamer")), ("length", features(short)["length"])):
            if key[1]:
                total = sums.setdefault(key, [0.0, 0])
                total[0] += relative
                total[1] += 1
    points = {}
    for (name, value), (total, count) in sums.items():
        if count >= EXTERNAL_MIN_SHORTS:
            limit = EXTERNAL_MAX_POINTS[name]
            points[(name, value)] = max(-limit, min(limit, 2.0 * total / (count + EXTERNAL_PRIOR)))
    return points


def competitor_examples(shorts: list[dict[str, Any]], count: int = 4) -> str:
    """Titles that do best and worst on the big clip channels, relative to each channel."""
    lines = []
    for theme, label in (("gaming", "jeux video"), ("irl", "IRL / Just Chatting")):
        own = [short for short in shorts if short.get("theme") == theme and short.get("title")]
        by_channel: dict[str, list[int]] = {}
        for short in own:
            by_channel.setdefault(short["channel_id"], []).append(short.get("views", 0))
        medians = {channel: statistics.median(values) for channel, values in by_channel.items()}
        ranked = sorted(own, key=lambda short: math.log10(short.get("views", 0) + 1) - math.log10(medians[short["channel_id"]] + 1))
        if len(ranked) < 2 * count:
            continue
        lines.append(f"Titres de Shorts {label} qui marchent le MIEUX sur les grosses chaines de clips :")
        lines += [f"- {short['title']} ({short['seconds']} s)" for short in reversed(ranked[-count:])]
        lines.append("Et le MOINS bien :")
        lines += [f"- {short['title']} ({short['seconds']} s)" for short in ranked[:count]]
    return "\n".join(lines)


def _uploaded(entry: dict[str, Any]) -> datetime | None:
    try:
        return datetime.fromisoformat(entry["uploaded_at"])
    except (KeyError, TypeError, ValueError):
        return None


def examples_text(output_dir: Path, count: int = 4) -> str:
    """The published Shorts that did best and worst, shown to Gemini as examples."""
    try:
        history = json.loads((output_dir / "published_shorts.json").read_text(encoding="utf-8"))["shorts"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return ""
    scores = performance(history)
    if len(scores) < 2 * count:
        return ""
    ranked = sorted(
        (entry for entry in history if entry.get("video_id") in scores and entry.get("title")),
        key=lambda entry: scores[entry["video_id"]],
    )

    def describe(entry: dict[str, Any]) -> str:
        details = [f"{entry.get('seconds', '?')} s", f"moment : {entry.get('source') or 'transcript'}"]
        if entry.get("retention_pct") is not None:
            details.append(f"regarde a {entry['retention_pct']:.0f} %")
        details.append(f"{_views(entry)} vues")
        return f"- {entry.get('title', '')} | accroche : {entry.get('hook') or '-'} | " + ", ".join(details)

    return (
        "Les Shorts deja publies qui ont le MIEUX marche (vues, part regardee, likes) :\n"
        + "\n".join(describe(entry) for entry in reversed(ranked[-count:]))
        + "\nCeux qui ont le MOINS bien marche :\n"
        + "\n".join(describe(entry) for entry in ranked[:count])
        + "\nInspire-toi de ce qui differencie les premiers des seconds (sans copier les sujets)."
    )
