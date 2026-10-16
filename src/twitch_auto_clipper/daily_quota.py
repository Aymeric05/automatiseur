"""Daily request budget for an external API, persisted across restarts."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Callable


def _pacific_offset(moment: datetime) -> timedelta:
    """UTC offset of US Pacific time at ``moment`` (US daylight saving rules since 2007)."""
    march = datetime(moment.year, 3, 8, tzinfo=timezone.utc)
    november = datetime(moment.year, 11, 1, tzinfo=timezone.utc)
    # 2:00 local time on the second Sunday of March / the first Sunday of November.
    dst_start = march + timedelta(days=(6 - march.weekday()) % 7, hours=10)
    dst_end = november + timedelta(days=(6 - november.weekday()) % 7, hours=9)
    return timedelta(hours=-7 if dst_start <= moment < dst_end else -8)


def _pacific_midnight(day: date) -> datetime:
    """Midnight Pacific time of ``day``, in UTC (07:00 in summer, 08:00 in winter)."""
    midnight = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    # 08:00 UTC is still before 2:00 local time, so it has midnight's offset.
    return midnight - _pacific_offset(midnight + timedelta(hours=8))


class DailyQuota:
    """Number of requests allowed per quota day.

    Quota days follow Google's reset of YouTube and Gemini quotas: midnight
    Pacific time (09:00 in Paris most of the year). The day is also closed early when the service itself refuses a request
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
        now = self._clock()
        return (now + _pacific_offset(now)).date().isoformat()

    def day(self) -> str:
        """The current quota day (its Pacific date)."""
        return self._today()

    def next_reset(self) -> datetime:
        return _pacific_midnight(date.fromisoformat(self._today()) + timedelta(days=1))

    def available(self) -> bool:
        state = self._state()
        return not state["exhausted"] and state["used"] < self.daily_limit

    def remaining(self) -> int:
        state = self._state()
        return 0 if state["exhausted"] else max(0, self.daily_limit - state["used"])

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


class RollingQuota:
    """At most ``limit`` uses in any 24 hours, and a pause after a refusal.

    YouTube limits a channel's uploads over a rolling 24 hours, not per
    calendar day: it refused uploads the day after a batch of 10, although the
    API quota day had reset. Uses are persisted across restarts.
    """

    WINDOW = timedelta(hours=24)
    RETRY_AFTER_REFUSAL = timedelta(hours=1)  # YouTube does not say when it accepts again

    def __init__(
        self,
        path: Path,
        limit: int,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if limit < 1:
            raise ValueError("limit must be positive")
        self.path = path
        self.limit = limit
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def remaining(self) -> int:
        uses, retry_after = self._state()
        if retry_after is not None and self._clock() < retry_after:
            return 0
        return max(0, self.limit - len(uses))

    def available(self) -> bool:
        return self.remaining() > 0

    def record_use(self) -> None:
        uses, _ = self._state()
        self._write([*uses, self._clock()], None)  # an accepted upload ends any pause

    def mark_exhausted(self) -> None:
        """YouTube refused: pause, then try again."""
        uses, _ = self._state()
        self._write(uses, self._clock() + self.RETRY_AFTER_REFUSAL)

    def next_reset(self) -> datetime:
        """When an upload should be possible again."""
        uses, retry_after = self._state()
        moments = [self._clock()]
        if retry_after is not None:
            moments.append(retry_after)
        if len(uses) >= self.limit:
            moments.append(sorted(uses)[len(uses) - self.limit] + self.WINDOW)
        return max(moments)

    def _state(self) -> tuple[list[datetime], datetime | None]:
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {}
        if not isinstance(state, dict):
            state = {}
        now = self._clock()
        uses = []
        for value in state.get("uses") or []:
            try:
                moment = datetime.fromisoformat(value)
            except (TypeError, ValueError):
                continue
            if now - moment < self.WINDOW:
                uses.append(moment)
        try:
            retry_after = datetime.fromisoformat(state["retry_after"]) if state.get("retry_after") else None
        except (TypeError, ValueError):
            retry_after = None
        return uses, retry_after

    def _write(self, uses: list[datetime], retry_after: datetime | None) -> None:
        state = {
            "uses": [moment.isoformat() for moment in uses],
            "retry_after": retry_after.isoformat() if retry_after else None,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = self.path.with_name(f"{self.path.name}.tmp")
            temporary_path.write_text(json.dumps(state), encoding="utf-8")
            temporary_path.replace(self.path)
        except OSError:
            pass  # a lost count is harmless: YouTube's own refusal pauses uploads anyway
