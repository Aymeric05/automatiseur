"""Polling and change detection for discovered Twitch live streams."""

from collections import Counter
from dataclasses import dataclass, replace
from threading import Event
import time
from typing import Callable

from .clip_budget import (
    DEFAULT_CLIP_BUDGET_POLICY,
    ClipBudgetPolicy,
    clip_count_for_stream,
)
from .twitch_api import LiveStream, TwitchAPIClient, TwitchAPIError


@dataclass(frozen=True)
class MonitoredStream:
    stream: LiveStream
    clip_budget: int  # from current viewers while live; from the peak once ended
    peak_viewer_count: int | None = None  # highest viewers seen in this session

    @property
    def peak_viewers(self) -> int:
        return max(self.peak_viewer_count or 0, self.stream.viewer_count)


@dataclass(frozen=True)
class ViewerCountChange:
    stream: MonitoredStream
    previous_viewer_count: int
    previous_clip_budget: int | None = None


@dataclass(frozen=True)
class MonitoringCycle:
    streams: tuple[MonitoredStream, ...] = ()  # tracked streams still live
    newly_discovered: tuple[MonitoredStream, ...] = ()
    viewer_count_changes: tuple[ViewerCountChange, ...] = ()
    ended_streams: tuple[MonitoredStream, ...] = ()
    error: str | None = None
    scanned_stream_count: int = 0
    duration_seconds: float = 0.0
    status_check_error: str | None = None


class TwitchStreamMonitor:
    """Poll live English streams and report meaningful changes per session.

    Only streams with a non-zero clip budget start being tracked, so the
    stream list is fetched only down to the lowest eligible viewer count.
    A tracked stream missing from that list may simply have dropped below the
    threshold: its broadcaster is then checked directly, and the stream is
    ended only after ``end_confirmation_polls`` successful offline checks.
    """

    def __init__(
        self,
        client: TwitchAPIClient | None = None,
        polling_interval_seconds: float = 60.0,
        budget_policy: ClipBudgetPolicy = DEFAULT_CLIP_BUDGET_POLICY,
        end_confirmation_polls: int = 3,
    ) -> None:
        if polling_interval_seconds <= 0:
            raise ValueError("polling_interval_seconds must be positive")
        if end_confirmation_polls < 1:
            raise ValueError("end_confirmation_polls must be positive")
        self.client = client or TwitchAPIClient()
        self.polling_interval_seconds = polling_interval_seconds
        self.budget_policy = budget_policy
        self.end_confirmation_polls = end_confirmation_polls
        self._active_streams: dict[str, MonitoredStream] = {}
        self._missing_polls: dict[str, int] = {}

    def poll_once(self) -> MonitoringCycle:
        """Fetch and classify one snapshot; API errors are returned, not raised."""
        started = time.monotonic()
        try:
            streams = self.client.fetch_english_streams(
                min_viewers=self.budget_policy.minimum_eligible_viewers
            )
        except TwitchAPIError as error:
            return MonitoringCycle(error=str(error), duration_seconds=time.monotonic() - started)

        listed = {
            stream.stream_id: stream
            for stream in streams
            if stream.language.lower() == "en"
        }

        # Tracked streams absent from the list: ask Twitch directly.
        missing = [
            monitored for stream_id, monitored in self._active_streams.items()
            if stream_id not in listed
        ]
        live_by_broadcaster: dict[str, LiveStream] | None = {}
        status_check_error = None
        if missing:
            try:
                live_by_broadcaster = self.client.fetch_live_streams_by_user_ids(
                    [monitored.stream.broadcaster_id for monitored in missing]
                )
            except TwitchAPIError as error:
                live_by_broadcaster = None  # unknown: this cycle is not a confirmation
                status_check_error = str(error)

        current: dict[str, MonitoredStream] = {}
        newly_discovered: list[MonitoredStream] = []
        viewer_count_changes: list[ViewerCountChange] = []

        def observe(stream: LiveStream) -> None:
            # Sessions are keyed by stream_id: a relaunch gets a new id, hence a fresh peak.
            previous = self._active_streams.get(stream.stream_id)
            monitored = MonitoredStream(
                stream,
                clip_count_for_stream(stream, self.budget_policy),
                max(previous.peak_viewers if previous else 0, stream.viewer_count),
            )
            if previous is None:
                if monitored.clip_budget <= 0:
                    return  # not eligible and not tracked: ignore
                newly_discovered.append(monitored)
            elif previous.stream.viewer_count != stream.viewer_count:
                viewer_count_changes.append(
                    ViewerCountChange(monitored, previous.stream.viewer_count, previous.clip_budget)
                )
            current[stream.stream_id] = monitored
            self._missing_polls.pop(stream.stream_id, None)

        for stream in listed.values():
            observe(stream)

        ended: list[MonitoredStream] = []
        for monitored in missing:
            stream_id = monitored.stream.stream_id
            if live_by_broadcaster is None:
                current[stream_id] = monitored  # status unknown: keep, do not count
                continue
            live = live_by_broadcaster.get(monitored.stream.broadcaster_id)
            if live is not None and live.stream_id == stream_id:
                observe(live)  # still live, just below the listing threshold
                continue
            misses = self._missing_polls.get(stream_id, 0) + 1
            if misses >= self.end_confirmation_polls:
                self._missing_polls.pop(stream_id, None)
                # The VOD budget reflects the session's peak, not its final viewers.
                ended.append(replace(
                    monitored,
                    clip_budget=self.budget_policy.clips_for_viewers(monitored.peak_viewers),
                ))
            else:
                self._missing_polls[stream_id] = misses
                current[stream_id] = monitored

        self._active_streams = current
        return MonitoringCycle(
            streams=tuple(current.values()),
            newly_discovered=tuple(newly_discovered),
            viewer_count_changes=tuple(viewer_count_changes),
            ended_streams=tuple(ended),
            scanned_stream_count=len(streams),
            duration_seconds=time.monotonic() - started,
            status_check_error=status_check_error,
        )

    def run(
        self,
        on_cycle: Callable[[MonitoringCycle], None],
        stop_event: Event,
        max_cycles: int | None = None,
    ) -> None:
        """Poll until stopped (or after max_cycles), waiting between cycles."""
        cycles = 0
        while not stop_event.is_set():
            on_cycle(self.poll_once())
            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                return
            if stop_event.wait(self.polling_interval_seconds):
                return


def _describe(stream: LiveStream) -> str:
    return f"{stream.broadcaster_name} (@{stream.broadcaster_login})"


def format_monitoring_cycle(cycle: MonitoringCycle, verbose: bool = False) -> list[str]:
    """Summarise a cycle; one line per event only for eligible streams.

    Viewer changes are listed only when they change the clip budget, unless
    ``verbose`` is set, which also lists every tracked stream.
    """
    if cycle.error:
        return [f"Erreur Twitch : {cycle.error} ({cycle.duration_seconds:.1f}s)"]

    lines = [
        f"Cycle Twitch : {cycle.scanned_stream_count} streams anglais parcourus, "
        f"{sum(1 for m in cycle.streams if m.clip_budget > 0)} avec budget > 0, "
        f"{len(cycle.streams)} suivis ({cycle.duration_seconds:.1f}s)"
    ]
    tiers = Counter(m.clip_budget for m in cycle.streams if m.clip_budget > 0)
    if tiers:
        lines.append(
            "Budgets : "
            + ", ".join(f"{budget} clips x{count}" for budget, count in sorted(tiers.items(), reverse=True))
        )
    for monitored in cycle.newly_discovered:
        lines.append(
            f"Nouveau stream : {_describe(monitored.stream)} "
            f"- {monitored.stream.viewer_count} viewers - budget : {monitored.clip_budget} clips"
        )
    for change in cycle.viewer_count_changes:
        if not verbose and change.previous_clip_budget == change.stream.clip_budget:
            continue
        lines.append(
            f"Viewers modifies : {_describe(change.stream.stream)} "
            f"- {change.previous_viewer_count} -> {change.stream.stream.viewer_count} "
            f"- budget : {change.stream.clip_budget} clips"
        )
    for monitored in cycle.ended_streams:
        lines.append(
            f"Stream termine : {_describe(monitored.stream)} "
            f"- stream ID : {monitored.stream.stream_id} "
            f"- pic : {monitored.peak_viewers} viewers - budget : {monitored.clip_budget} clips"
        )
    if cycle.status_check_error:
        lines.append(
            "Verification des streams absents impossible (cycle non compte) : "
            f"{cycle.status_check_error}"
        )
    if verbose:
        for monitored in sorted(cycle.streams, key=lambda m: -m.stream.viewer_count):
            lines.append(
                f"  suivi : {_describe(monitored.stream)} - "
                f"{monitored.stream.viewer_count} viewers (pic {monitored.peak_viewers}) "
                f"- budget : {monitored.clip_budget} clips"
            )
    return lines
