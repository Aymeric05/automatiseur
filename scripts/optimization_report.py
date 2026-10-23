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
    watched = set(load("studied_videos.json", []))
    ranked_own = sorted((e for e in measured if e["video_id"] not in watched), key=lambda e: scores[e["video_id"]])
    if len(ranked_own) >= 2:
        print(f"ours not yet watched: best {ranked_own[-1]['video_id']} ({(ranked_own[-1].get('title') or '')[:40]}) | "
              f"worst {ranked_own[0]['video_id']} ({(ranked_own[0].get('title') or '')[:40]})")
    fresh = [e for e in entries if e.get("uploaded_at", "") >= (NOW - timedelta(days=1)).isoformat()][-3:]
    if fresh:
        print("ours published in the last 24 h (quality check): " + ", ".join(e["video_id"] for e in fresh))
    for label, since in CHANGES.items():
        before = [scores[e["video_id"]] for e in measured if e.get("uploaded_at", "") < since]
        after = [scores[e["video_id"]] for e in measured if e.get("uploaded_at", "") >= since]
        if after:
            print(f"change '{label}': perf before n={len(before)} median={median(before)} / after n={len(after)} median={median(after)}")

tests = json.loads(Path("config/experiments.json").read_text(encoding="utf-8")).get("experiments", [])
print("\n## A/B tests running" + ("" if tests else ": none"))
for test in tests:
    scores = PerformanceModel(history, test["channel"], NOW).performance
    print(f"{test['id']} ({test['channel']}, since {test.get('started')}): {test.get('description', '')[:80]}")
    for side in ("A", "B"):
        group = [e for e in history if e.get("channel", "gaming") == test["channel"]
                 and (e.get("experiments") or {}).get(test["id"]) == side and e["video_id"] in scores]
        print(f"  {side}: measured n={len(group)} vods={len({e.get('vod_id') for e in group})} perf={median([scores[e['video_id']] for e in group])} "
              f"retention={median([e['retention_pct'] for e in group if isinstance(e.get('retention_pct'), (int, float))])} "
              f"views={median([e.get('views_3d', e.get('views_1d', 0)) for e in group])}")

guide = load("format_guide.json", {})
competitors = load("competitor_shorts.json", {})
studied = set(load("studied_videos.json", []))
EMOJI = re.compile("[\U0001F000-\U0001FFFF\u2600-\u27BF]")


def title_traits(title: str) -> dict:
    words = title.split()
    return {
        "chars": len(title), "emoji": bool(EMOJI.search(title)), "question": "?" in title,
        "exclaim": "!" in title, "hashtag": "#" in title,
        "caps_word": any(len(w) > 3 and w.isupper() for w in words),
    }


def summary(shorts: list, seconds_key: str = "seconds") -> str:
    traits = [title_traits(s.get("title") or "") for s in shorts]
    share = lambda key: f"{100 * sum(t[key] for t in traits) // max(len(traits), 1)}%"
    return (f"n={len(shorts)} sec={median([s.get(seconds_key) or 0 for s in shorts])} "
            f"title_chars={median([t['chars'] for t in traits])} emoji={share('emoji')} ?={share('question')} "
            f"!={share('exclaim')} #={share('hashtag')} CAPS={share('caps_word')}")


print()
print(f"## competitors: refreshed {competitors.get('refreshed_at')}, guide studied {guide.get('studied_at')}, "
      f"{len(studied)} videos already watched by Gemini")
for theme in ("gaming", "irl"):
    shorts = [s for s in competitors.get("shorts", []) if s.get("theme") == theme]
    if len(shorts) < 9:
        continue
    by_channel: dict = {}
    for s in shorts:
        by_channel.setdefault(s["channel_id"], []).append(s["views"])
    medians = {c: statistics.median(v) for c, v in by_channel.items()}
    ranked = sorted(shorts, key=lambda s: (s["views"] + 1) / (medians[s["channel_id"]] + 1))
    third = len(ranked) // 3
    ours = [e for e in history if e.get("channel", "gaming") == theme][-60:]
    print(f"{theme} ({len(by_channel)} channels), relative to each channel's median views:")
    print(f"  top third   : {summary(ranked[-third:])}")
    print(f"  bottom third: {summary(ranked[:third])}")
    print(f"  ours (last 60): {summary(ours)}")
    print(f"  guide ideal {guide.get(theme, {}).get('ideal_seconds')}; top 5 not yet watched: "
          + ", ".join([s["video_id"] for s in reversed(ranked[-20:]) if s["video_id"] not in studied][:5])
          + " | bottom 5 not yet watched: " + ", ".join([s["video_id"] for s in ranked[:20] if s["video_id"] not in studied][:5]))

log = Path(OUTPUT / "monitor.log")
lines = log.read_text(encoding="utf-8", errors="replace").splitlines()[-3000:] if log.exists() else []
errors = Counter(re.sub(r"\d+", "#", line)[:70] for line in lines if re.search(r"Erreur|Traceback|echec|Exception", line))
print("\n## log (last 3000 lines): top errors")
for text, count in errors.most_common(6):
    print(f"{count}x {text}")
published = sum("Publication VOD" in line and "[publie]" in line for line in lines)
pipelines = Counter(line.split(":")[-1].strip()[:20] for line in lines if line.startswith("Pipeline VOD"))
print(f"uploads ok: {published}; pipelines: {dict(pipelines)}")
funnels = [line.split("entonnoir : ")[1].split(";")[0].rstrip(")") for line in lines if "entonnoir : " in line]
print("moments kept per step, last VODs:", " | ".join(funnels[-8:]) or "none yet")

# Production: Shorts rendered (rendered_at, recorded from 2026-10-23) vs published, and the reserve now.
print("\n## production (rendered vs published per 24 h; reserve target 30)")
made, reserve = Counter(), Counter()
for manifest in OUTPUT.glob("*_processing.json"):
    data = json.loads(manifest.read_text(encoding="utf-8"))
    uploaded = data.get("youtube_uploads") or {}
    for key, short in (data.get("generated_shorts") or {}).items():
        channel = short.get("channel") or "gaming"
        if (short.get("rendered_at") or "") >= (NOW - timedelta(days=1)).isoformat():
            made[channel] += 1
        if data.get("automation_status") == "completed" and key not in uploaded and (OUTPUT / short.get("file", "")).exists():
            reserve[channel] += 1
for channel in ("gaming", "irl"):
    sent = sum(e.get("channel", "gaming") == channel and e.get("uploaded_at", "") >= (NOW - timedelta(days=1)).isoformat() for e in history)
    print(f"{channel}: rendered {made[channel]}, published {sent}, reserve {reserve[channel]}/30")
