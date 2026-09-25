"""Polling and change detection for discovered Twitch live streams."""

from dataclasses import dataclass
from threading import Event
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
    clip_budget: int


@dataclass(frozen=True)
class ViewerCountChange:
    stream: MonitoredStream
    previous_viewer_count: int


@dataclass(frozen=True)
class MonitoringCycle:
    streams: tuple[MonitoredStream, ...] = ()
    newly_discovered: tuple[MonitoredStream, ...] = ()
    viewer_count_changes: tuple[ViewerCountChange, ...] = ()
    ended_streams: tuple[MonitoredStream, ...] = ()
    error: str | None = None


class TwitchStreamMonitor:
    """Poll live English streams and report meaningful changes per session."""

    def __init__(
        self,
        client: TwitchAPIClient | None = None,
        polling_interval_seconds: float = 60.0,
        budget_policy: ClipBudgetPolicy = DEFAULT_CLIP_BUDGET_POLICY,
    ) -> None:
        if polling_interval_seconds <= 0:
            raise ValueError("polling_interval_seconds must be positive")
        self.client = client or TwitchAPIClient()
        self.polling_interval_seconds = polling_interval_seconds
        self.budget_policy = budget_policy
        self._known_streams: dict[str, MonitoredStream] = {}
        self._active_streams: dict[str, MonitoredStream] = {}

    def poll_once(self) -> MonitoringCycle:
        """Fetch and classify one snapshot; API errors are returned, not raised."""
        try:
            streams = self.client.fetch_english_streams()
        except TwitchAPIError as error:
            return MonitoringCycle(error=str(error))

        current: list[MonitoredStream] = []
        current_by_id: dict[str, MonitoredStream] = {}
        newly_discovered: list[MonitoredStream] = []
        viewer_count_changes: list[ViewerCountChange] = []

        for stream in streams:
            if stream.language.lower() != "en":
                continue
            monitored = MonitoredStream(
                stream=stream,
                clip_budget=clip_count_for_stream(stream, self.budget_policy),
            )
            current.append(monitored)
            current_by_id[stream.stream_id] = monitored
            previous = self._known_streams.get(stream.stream_id)
            if previous is None:
                newly_discovered.append(monitored)
            elif previous.stream.viewer_count != stream.viewer_count:
                viewer_count_changes.append(
                    ViewerCountChange(
                        stream=monitored,
                        previous_viewer_count=previous.stream.viewer_count,
                    )
                )
            self._known_streams[stream.stream_id] = monitored

        ended_streams = tuple(
            monitored
            for stream_id, monitored in self._active_streams.items()
            if stream_id not in current_by_id
        )
        self._active_streams = current_by_id

        return MonitoringCycle(
            streams=tuple(current),
            newly_discovered=tuple(newly_discovered),
            viewer_count_changes=tuple(viewer_count_changes),
            ended_streams=ended_streams,
        )

    def run(
        self,
        on_cycle: Callable[[MonitoringCycle], None],
        stop_event: Event,
    ) -> None:
        """Poll until stopped, waiting the configured interval between cycles."""
        while not stop_event.is_set():
            on_cycle(self.poll_once())
            if stop_event.wait(self.polling_interval_seconds):
                return


def format_monitoring_cycle(cycle: MonitoringCycle) -> list[str]:
    """Format discovered streams and viewer-count changes for the CLI."""
    lines = []
    for monitored in cycle.newly_discovered:
        stream = monitored.stream
        lines.append(
            f"Nouveau stream : {stream.broadcaster_name} (@{stream.broadcaster_login}) "
            f"- {stream.viewer_count} viewers - budget : {monitored.clip_budget} clips"
        )
    for change in cycle.viewer_count_changes:
        stream = change.stream.stream
        lines.append(
            f"Viewers modifies : {stream.broadcaster_name} (@{stream.broadcaster_login}) "
            f"- {change.previous_viewer_count} -> {stream.viewer_count} "
            f"- budget : {change.stream.clip_budget} clips"
        )
    for monitored in cycle.ended_streams:
        stream = monitored.stream
        lines.append(
            f"Stream termine : {stream.broadcaster_name} (@{stream.broadcaster_login}) "
            f"- stream ID : {stream.stream_id}"
        )
    if cycle.error:
        lines.append(f"Erreur Twitch : {cycle.error}")
    elif not lines:
        lines.append("Aucun nouveau stream ou changement de viewers.")
    return lines