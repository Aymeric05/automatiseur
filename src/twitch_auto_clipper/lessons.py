"""What the app learns from the Shorts it made for nothing and from the views of the others.

Every Short pushed out of a reserve, or never rendered because it could not
enter it, is recorded with the reason (``rejected_shorts.json``). Once a day,
Gemini compares them with the published Shorts and their views, and writes a
few concrete rules (``selection_lessons.txt``) that the moment selection then
follows, so the same kind of weak Short is not made again.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Callable

from .gemini_evaluation import GEMINI_FALLBACK_MODELS, _generate_json

REJECTED_FILE = "rejected_shorts.json"
LESSONS_FILE = "selection_lessons.txt"
MAX_REJECTED_KEPT = 1000
LESSONS_INTERVAL = timedelta(hours=24)
LESSONS_SCHEMA = {
    "type": "object",
    "properties": {"lessons": {"type": "array", "items": {"type": "string"}}},
    "required": ["lessons"],
}


def record_rejection(output_dir: Path, entry: dict[str, Any], clock: Callable[[], datetime] | None = None) -> None:
    """Remember a Short made (or about to be made) for nothing, and why."""
    path = output_dir / REJECTED_FILE
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        entries = []
    entries = entries if isinstance(entries, list) else []
    entries.append({"at": (clock or (lambda: datetime.now(timezone.utc)))().isoformat(timespec="seconds"), **entry})
    temporary = path.with_name(f"{path.name}.tmp")
    try:
        temporary.write_text(json.dumps(entries[-MAX_REJECTED_KEPT:], ensure_ascii=False, indent=1), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        pass  # only a statistic: never blocks the reserve


def load_lessons(output_dir: Path) -> str:
    try:
        return (output_dir / LESSONS_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def learn_lessons(
    output_dir: Path,
    model: str = "gemini-3.6-flash",
    quota_dir: Path | None = None,
    daily_limit: int = 20,
    fallback_models: tuple[str, ...] = GEMINI_FALLBACK_MODELS,
    clock: Callable[[], datetime] | None = None,
) -> str | None:
    """Once a day, new rules for the selection; returns a summary line when written."""
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    path = output_dir / LESSONS_FILE
    try:
        if now - datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < LESSONS_INTERVAL:
            return None
    except OSError:
        pass
    week_ago = now - timedelta(days=7)
    try:
        rejected = [
            entry for entry in json.loads((output_dir / REJECTED_FILE).read_text(encoding="utf-8"))
            if datetime.fromisoformat(entry["at"]) >= week_ago
        ][-80:]
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        rejected = []
    try:
        history = json.loads((output_dir / "published_shorts.json").read_text(encoding="utf-8"))["shorts"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        history = []
    measured = sorted(
        (entry for entry in history if isinstance(entry.get("views_1d", entry.get("views")), int)),
        key=lambda entry: entry.get("views_3d", entry.get("views_1d", entry.get("views", 0))),
    )
    published = measured[-10:] + measured[:10]
    if len(rejected) + len(published) < 10:
        return None
    keys = ("channel", "streamer", "title", "gemini_score", "source", "emotion", "seconds",
            "views", "views_1d", "views_3d", "retention_pct", "reason", "justification")
    prompt = (
        "Tu choisis des moments de lives Twitch pour en faire des YouTube Shorts. rejected liste "
        "des Shorts faits pour rien (ecartes car moins bons que ceux deja en reserve) avec la "
        "raison ; published liste des Shorts publies avec leurs vues et la part regardee "
        "(retention_pct). Deduis-en 5 a 8 regles courtes, concretes et generales pour mieux choisir "
        "les prochains moments : ce qu'il faut eviter et ce qu'il faut privilegier (type de moment, "
        "comprehension sans contexte, duree, chute...). Pas de regle sur un streamer precis. "
        'Retourne un JSON {"lessons":["..."]}.\n\n'
        + json.dumps({
            "rejected": [{key: entry.get(key) for key in keys if entry.get(key) is not None} for entry in rejected],
            "published": [{key: entry.get(key) for key in keys if entry.get(key) is not None} for entry in published],
        }, ensure_ascii=False)
    )
    text, _ = _generate_json(prompt, LESSONS_SCHEMA, model, quota_dir, daily_limit, fallback_models)
    lessons = [str(line).strip() for line in json.loads(text).get("lessons", []) if str(line).strip()][:8]
    if not lessons:
        return None
    path.write_text("\n".join(f"- {line}" for line in lessons) + "\n", encoding="utf-8")
    return f"Lecons de selection mises a jour ({len(rejected)} Shorts ecartes, {len(published)} publies analyses)."
