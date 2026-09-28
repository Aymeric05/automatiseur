"""Resolve and download archived VODs for ended monitored streams."""

from dataclasses import dataclass
import json
from pathlib import Path
from threading import Event
from typing import Callable

from .twitch import TwitchDownloadError, download_twitch_vod
from .twitch_api import TwitchAPIClient, TwitchAPIError
from .twitch_monitor import (
    MonitoringCycle,
    MonitoredStream,
    TwitchStreamMonitor,
)


@dataclass(frozen=True)
class VODAcquisitionResult:
    stream_id: str
    clip_budget: int
    status: str
    broadcaster_id: str
    broadcaster_login: str
    broadcaster_name: str
    vod_id: str | None = None
    downloaded_path: Path | None = None
    error: str | None = None


@dataclass(frozen=True)
class VODMonitoringCycle:
    monitoring_cycle: MonitoringCycle
    acquisition_results: tuple[VODAcquisitionResult, ...] = ()


class TwitchVODAcquisitionManager:
    """Acquire each eligible ended stream's VOD at most once per state file."""

    def __init__(
        self,
        monitor: TwitchStreamMonitor | None = None,
        api_client: TwitchAPIClient | None = None,
        input_dir: Path = Path("data/input"),
        state_path: Path = Path("data/output/twitch_vod_state.json"),
        downloader: Callable[[str, Path], Path] | None = None,
    ) -> None:
        self.monitor = monitor or TwitchStreamMonitor()
        self.api_client = api_client or self.monitor.client
        self.input_dir = input_dir
        self.state_path = state_path
        self.downloader = downloader or download_twitch_vod
        self._processed_streams: dict[str, str] = {}
        self._processed_vod_ids: set[str] = set()
        self._pending_streams: dict[str, MonitoredStream] = {}
        self._load_state()

    def poll_once(self) -> VODMonitoringCycle:
        cycle = self.monitor.poll_once()
        return VODMonitoringCycle(cycle, self.process_cycle(cycle))

    def process_cycle(
        self,
        cycle: MonitoringCycle,
    ) -> tuple[VODAcquisitionResult, ...]:
        if cycle.error:
            return ()

        for monitored in cycle.ended_streams:
            stream_id = monitored.stream.stream_id
            self._pending_streams.setdefault(stream_id, monitored)

        results = []
        for stream_id, monitored in tuple(self._pending_streams.items()):
            if monitored.clip_budget <= 0:
                results.append(self._result(monitored, "skipped_zero_budget"))
                del self._pending_streams[stream_id]
                continue

            if stream_id in self._processed_streams:
                vod_id = self._processed_streams[stream_id]
                downloaded_path = self.input_dir / f"{vod_id}.mp4"
                results.append(
                    self._result(
                        monitored,
                        "already_processed",
                        vod_id=vod_id,
                        downloaded_path=(downloaded_path if downloaded_path.is_file() else None),
                    )
                )
                del self._pending_streams[stream_id]
                continue

            try:
                vod = self.api_client.find_vod_for_stream(
                    monitored.stream.broadcaster_id,
                    stream_id,
                )
            except TwitchAPIError as error:
                results.append(self._result(monitored, "error", error=str(error)))
                continue

            if vod is None:
                results.append(self._result(monitored, "vod_not_available"))
                continue

            if vod.vod_id in self._processed_vod_ids:
                self._remember_processed(stream_id, vod.vod_id)
                known_path = self.input_dir / f"{vod.vod_id}.mp4"
                results.append(
                    self._result(
                        monitored,
                        "already_processed",
                        vod_id=vod.vod_id,
                        downloaded_path=known_path if known_path.is_file() else None,
                    )
                )
                del self._pending_streams[stream_id]
                continue

            existing_path = self.input_dir / f"{vod.vod_id}.mp4"
            if existing_path.is_file():
                self._remember_processed(stream_id, vod.vod_id)
                results.append(
                    self._result(
                        monitored,
                        "already_downloaded",
                        vod_id=vod.vod_id,
                        downloaded_path=existing_path,
                    )
                )
                del self._pending_streams[stream_id]
                continue

            vod_url = f"https://www.twitch.tv/videos/{vod.vod_id}"
            try:
                downloaded_path = self.downloader(vod_url, self.input_dir)
                self._remember_processed(stream_id, vod.vod_id)
            except (TwitchDownloadError, OSError, ValueError) as error:
                results.append(self._result(monitored, "error", vod_id=vod.vod_id, error=str(error)))
                continue

            results.append(
                self._result(
                    monitored,
                    "downloaded",
                    vod_id=vod.vod_id,
                    downloaded_path=downloaded_path,
                )
            )
            del self._pending_streams[stream_id]

        return tuple(results)

    def run(
        self,
        on_cycle: Callable[[VODMonitoringCycle], None],
        stop_event: Event,
        max_cycles: int | None = None,
    ) -> None:
        def handle_monitoring_cycle(cycle: MonitoringCycle) -> None:
            on_cycle(VODMonitoringCycle(cycle, self.process_cycle(cycle)))

        self.monitor.run(handle_monitoring_cycle, stop_event, max_cycles=max_cycles)

    def _load_state(self) -> None:
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Unable to read Twitch VOD state: {error}") from error

        processed_streams = state.get("processed_streams", {})
        processed_vod_ids = state.get("processed_vod_ids", [])
        if not isinstance(processed_streams, dict) or not isinstance(processed_vod_ids, list):
            raise ValueError("Twitch VOD state has an invalid format.")
        self._processed_streams = {
            str(stream_id): str(vod_id)
            for stream_id, vod_id in processed_streams.items()
        }
        self._processed_vod_ids = set(processed_vod_ids) | set(
            self._processed_streams.values()
        )

    def _remember_processed(self, stream_id: str, vod_id: str) -> None:
        processed_streams = {**self._processed_streams, stream_id: vod_id}
        processed_vod_ids = self._processed_vod_ids | {vod_id}
        state = {
            "processed_streams": processed_streams,
            "processed_vod_ids": sorted(processed_vod_ids),
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.state_path.with_name(f"{self.state_path.name}.tmp")
        temporary_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        temporary_path.replace(self.state_path)
        self._processed_streams = processed_streams
        self._processed_vod_ids = processed_vod_ids

    @staticmethod
    def _result(
        monitored: MonitoredStream,
        status: str,
        vod_id: str | None = None,
        downloaded_path: Path | None = None,
        error: str | None = None,
    ) -> VODAcquisitionResult:
        return VODAcquisitionResult(
            stream_id=monitored.stream.stream_id,
            clip_budget=monitored.clip_budget,
            status=status,
            broadcaster_id=monitored.stream.broadcaster_id,
            broadcaster_login=monitored.stream.broadcaster_login,
            broadcaster_name=monitored.stream.broadcaster_name,
            vod_id=vod_id,
            downloaded_path=downloaded_path,
            error=error,
        )


def format_vod_acquisition_result(result: VODAcquisitionResult) -> str:
    if result.status == "downloaded":
        return f"VOD {result.vod_id} telecharge : {result.downloaded_path}"
    if result.status == "vod_not_available":
        return f"VOD pas encore disponible pour le stream {result.stream_id}; nouvel essai au prochain cycle."
    if result.status == "skipped_zero_budget":
        return f"Stream {result.stream_id} ignore : budget de clips nul."
    if result.status == "already_downloaded":
        return f"VOD {result.vod_id} deja present : {result.downloaded_path}"
    if result.status == "already_processed":
        return f"VOD {result.vod_id} deja traite pour le stream {result.stream_id}."
    return f"Erreur VOD pour le stream {result.stream_id} : {result.error}"