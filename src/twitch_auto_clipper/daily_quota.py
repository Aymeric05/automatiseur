"""Daily request budget for an external API, persisted across restarts."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Callable

# Google resets YouTube and Gemini daily quotas at midnight Pacific time, i.e.
# 07:00 or 08:00 UTC depending on daylight saving: days counted from 08:00 UTC
# never start before the real reset.
QUOTA_RESET_HOUR_UTC = 8


class DailyQuota:
    """Number of requests allowed per quota day.

    The day is also closed early when the service itself refuses a request
    for quota reasons, whatever the local count says.
    """

    def __init__(
        self,
        path: Path,
        daily_limit: int,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if daily_limit < 1:
            raise ValueError("daily_limit must be positive")
        self.path = path
        self.daily_limit = daily_limit
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _today(self) -> str:
        return (self._clock() - timedelta(hours=QUOTA_RESET_HOUR_UTC)).date().isoformat()

    def next_reset(self) -> datetime:
        day = date.fromisoformat(self._today()) + timedelta(days=1)
        return datetime(day.year, day.month, day.day, QUOTA_RESET_HOUR_UTC, tzinfo=timezone.utc)

    def available(self) -> bool:
        state = self._state()
        return not state["exhausted"] and state["used"] < self.daily_limit

    def record_use(self) -> None:
        state = self._state()
        state["used"] += 1
        self._write(state)

    def mark_exhausted(self) -> None:
        state = self._state()
        state["exhausted"] = True
        self._write(state)

    def _state(self) -> dict[str, Any]:
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = None
        if not isinstance(state, dict) or state.get("day") != self._today():
            return {"day": self._today(), "used": 0, "exhausted": False}
        return {
            "day": state["day"],
            "used": int(state.get("used", 0)),
            "exhausted": bool(state.get("exhausted")),
        }

    def _write(self, state: dict[str, Any]) -> None:
        # A lost count is harmless: the service's own refusal closes the day anyway.
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = self.path.with_name(f"{self.path.name}.tmp")
            temporary_path.write_text(json.dumps(state), encoding="utf-8")
            temporary_path.replace(self.path)
        except OSError:
            pass
