"""Compact report for the daily optimization loop (docs/optimization_journal.md).

Prints, in ~50 lines, what the loop needs to decide: our measured Shorts per channel, which
features go with better results, the learned model's self-check, before/after comparisons
for the changes under evaluation, the competitors' guide, and recent errors in the log.
Run from the project root: python scripts/optimization_report.py
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import statistics
import sys

sys.path.insert(0, "src")
from twitch_auto_clipper.performance import PerformanceModel, external_points, features, performance  # noqa: E402

OUTPUT = Path("data/output")
NOW = datetime.now(timezone.utc)
# Change dates (from the journal) compared before/after: "label": (date, feature filter or None).
CHANGES = {
    "bounds by Gemini + no 30 s test": "2026-10-23T01:00:00+00:00",
    "format guide from competitors": "2026-10-23T01:28:00+00:00",
}


def load(name: str, default):
    try:
        return json.loads((OUTPUT / name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def median(values):
    return round(statistics.median(values), 1) if values else None


history = load("published_shorts.json", {}).get("shorts", [])
print(f"# Report {NOW:%Y-%m-%d %H:%M} UTC")
for channel in ("gaming", "irl"):
    entries = [e for e in history if e.get("channel", "gaming") == channel]
    model = PerformanceModel(history, channel, NOW)
    scores = model.performance
    recent = [e for e in entries if e.get("uploaded_at", "") >= (NOW - timedelta(days=1)).isoformat()]
    print(f"\n## {channel}: {len(entries)} published, {len(scores)} measured, {len(recent)} in the last 24 h")
    print(f"reliability={model.reliability:.2f} gemini_weight={model.gemini_weight:.2f}")
    measured = [e for e in entries if e["video_id"] in scores]
    print("median views", median([e.get("views_3d", e.get("views_1d", e.get("views", 0))) for e in measured]),
          "| median retention", median([e["retention_pct"] for e in measured if isinstance(e.get("retention_pct"), (int, float))]))
    effects = sorted(((value * 4, name, val) for (name, val), value in model.learned.items()), reverse=True)
    if effects:
        print("learned points (best, worst):", ", ".join(f"{n}={v} {p:+.1f}" for p, n, v in effects[:4]),
              "|", ", ".join(f"{n}={v} {p:+.1f}" for p, n, v in effects[-4:]))
    for label, since in CHANGES.items():
        before = [scores[e["video_id"]] for e in measured if e.get("uploaded_at", "") < since]
        after = [scores[e["video_id"]] for e in measured if e.get("uploaded_at", "") >= since]
        if after:
            print(f"change '{label}': perf before n={len(before)} median={median(before)} / after n={len(after)} median={median(after)}")

guide = load("format_guide.json", {})
competitors = load("competitor_shorts.json", {})
print(f"\n## competitors: refreshed {competitors.get('refreshed_at')}, guide studied {guide.get('studied_at')}")
for theme in ("gaming", "irl"):
    count = sum(s.get("theme") == theme for s in competitors.get("shorts", []))
    lengths = {k[1]: round(v, 2) for k, v in external_points(competitors.get("shorts", []), theme).items()}
    print(f"{theme}: {count} Shorts, length points {lengths}, ideal {guide.get(theme, {}).get('ideal_seconds')}")

log = Path(OUTPUT / "monitor.log")
lines = log.read_text(encoding="utf-8", errors="replace").splitlines()[-3000:] if log.exists() else []
errors = Counter(re.sub(r"\d+", "#", line)[:70] for line in lines if re.search(r"Erreur|Traceback|echec|Exception", line))
print("\n## log (last 3000 lines): top errors")
for text, count in errors.most_common(6):
    print(f"{count}x {text}")
published = sum("Publication VOD" in line and "[publie]" in line for line in lines)
pipelines = Counter(line.split(":")[-1].strip()[:20] for line in lines if line.startswith("Pipeline VOD"))
print(f"uploads ok: {published}; pipelines: {dict(pipelines)}")
