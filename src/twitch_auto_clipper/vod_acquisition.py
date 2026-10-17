"""Persistent queue of ended monitored streams whose VOD must be processed."""

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from functools import partial
import json
from pathlib import Path
import shutil
from threading import Event, Lock
from typing import Any, Callable, Iterator

from .twitch import TwitchDownloadError, download_twitch_vod
from .twitch_api import LiveStream, TwitchAPIClient, TwitchAPIError
from .twitch_monitor import (
    MonitoringCycle,
    TwitchStreamMonitor,
)

RETRY_BASE_SECONDS = 300  # first retry after 5 minutes, then twice as long each time
RETRY_MAX_SECONDS = 6 * 3600
MAX_ATTEMPTS = 8  # failed acquisitions or pipeline runs before a job is abandoned
VOD_WAIT_SECONDS = 24 * 3600  # still no VOD a day after the end: disabled or deleted
MIN_FREE_BYTES = 2 * 1024**3  # never start a download with less free space
# Unpublished Shorts expire after 48 hours: an older VOD is no longer worth processing.
MAX_JOB_AGE_SECONDS = 48 * 3600
TOP_STREAMER_CLIP_BUDGET = 20  # moments asked to Gemini for a streamer of the top list
# About what the worker processes within MAX_JOB_AGE_SECONDS: worse jobs are dropped.
MAX_QUEUED_JOBS = 40
MEMORY_SIZE = 2000  # processed and abandoned streams remembered (never queued twice)
AUDIO_SUFFIXES = frozenset({".mp4", ".m4a", ".aac", ".ts", ".webm", ".mkv", ".mp3", ".opus"})


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
    game_name: str = ""
    peak_viewers: int = 0


@dataclass(frozen=True)
class VODMonitoringCycle:
    monitoring_cycle: MonitoringCycle
    acquisition_results: tuple[VODAcquisitionResult, ...] = ()


def find_downloaded_audio(input_dir: Path, vod_id: str) -> Path | None:
    """Return the complete ``<vod_id>_audio.*`` file, ignoring yt-dlp temporary files."""
    for path in sorted(input_dir.glob(f"{vod_id}_audio.*")):
        if (
            path.suffix.lower() in AUDIO_SUFFIXES
            and ".part" not in path.name
            and ".temp." not in path.name
            and path.is_file()
            and path.stat().st_size > 0
        ):
            return path
    return None


class TwitchVODAcquisitionManager:
    """Queue each eligible ended stream once, then acquire its VOD audio.

    The monitoring thread only queues jobs (``process_cycle``, no network
    access). A worker takes the due jobs (``acquire_due``) and reports how the
    pipeline went (``record_automation``). Jobs stay in the state file until
    their VOD is fully processed, so a failure, Ctrl+C or a reboot never loses
    them: they are retried later with a growing delay and abandoned only after
    ``MAX_ATTEMPTS`` failures, or when no VOD appears within ``VOD_WAIT_SECONDS``.
    """

    def __init__(
        self,
        monitor: TwitchStreamMonitor | None = None,
        api_client: TwitchAPIClient | None = None,
        input_dir: Path = Path("data/input"),
        state_path: Path = Path("data/output/twitch_vod_state.json"),
        downloader: Callable[[str, Path], Path] | None = None,
        clock: Callable[[], datetime] | None = None,
        top_streamers: frozenset[str] = frozenset(),
        rate_limit: int | None = None,
    ) -> None:
        self.monitor = monitor or TwitchStreamMonitor()
        self.api_client = api_client or self.monitor.client
        self.input_dir = input_dir
        self.state_path = state_path
        # Only the audio is downloaded: the Shorts read their video from Twitch.
        # rate_limit (bytes per second) keeps the connection usable for everyone else.
        self.downloader = downloader or partial(
            download_twitch_vod, audio_only=True, quiet=True, rate_limit=rate_limit
        )
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        # Logins whose VODs get TOP_STREAMER_CLIP_BUDGET moments (hence go first).
        self.top_streamers = frozenset(login.lower() for login in top_streamers)
        self._lock = Lock()  # the monitoring thread queues, the worker thread acquires
        self._processed_streams: dict[str, str] = {}
        self._processed_vod_ids: set[str] = set()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._abandoned: dict[str, dict[str, Any]] = {}
        self._load_state()

    @property
    def pending_jobs(self) -> int:
        return len(self._jobs)

    def active_vod_ids(self) -> set[str]:
        """VODs whose job is still queued (their files must be kept)."""
        with self._lock:
            return {str(job["vod_id"]) for job in self._jobs.values() if job.get("vod_id")}

    def poll_once(self) -> VODMonitoringCycle:
        cycle = self.monitor.poll_once()
        return VODMonitoringCycle(cycle, self.process_cycle(cycle))

    def process_cycle(self, cycle: MonitoringCycle) -> tuple[VODAcquisitionResult, ...]:
        """Queue the eligible streams that ended in this cycle."""
        if cycle.error:
            return ()
        results = []
        now = _iso(self._clock())
        with self._lock:
            for monitored in cycle.ended_streams:
                stream = monitored.stream
                budget = self._budget(stream.broadcaster_login, monitored.clip_budget)
                if budget <= 0:
                    results.append(_result(stream, budget, "skipped_zero_budget"))
                elif stream.stream_id in self._processed_streams:
                    vod_id = self._processed_streams[stream.stream_id] or None
                    results.append(_result(stream, budget, "already_processed", vod_id=vod_id))
                elif stream.stream_id not in self._jobs:
                    self._jobs[stream.stream_id] = {
                        "stream": asdict(stream),
                        "clip_budget": budget,
                        "peak_viewers": monitored.peak_viewers,
                        "ended_at": now,
                        "vod_id": None,
                        "attempts": 0,
                        "next_attempt_at": now,
                        "last_error": None,
                    }
                    results.append(_result(stream, budget, "queued"))
            if any(result.status == "queued" for result in results):
                try:
                    self._save_state()
                except OSError as error:  # kept in memory, saved with the next change
                    results.append(_result(
                        cycle.ended_streams[0].stream, 0, "error",
                        error=f"file d'attente non sauvegardee : {error}",
                    ))
        return tuple(results)

    def acquire_due(self) -> Iterator[VODAcquisitionResult]:
        """Yield one acquisition per due job, biggest clip budget first.

        When VODs pile up, the top streamers' VODs are processed first, then
        the most watched streams (highest peak viewers), so a big live that
        just ended never waits behind smaller older ones.

        A "downloaded" or "already_downloaded" result must be followed by
        ``record_automation`` once the pipeline ran; every other result has
        already been rescheduled or abandoned here.
        """
        now = self._clock()
        with self._lock:
            self._purge_locked(now)
            due = sorted(
                # A VOD whose audio is already downloaded is finished first: its files never wait.
                (not self._started(job), *self._priority(stream_id, job))
                for stream_id, job in self._jobs.items()
                if _parse(job["next_attempt_at"]) <= now
            )
        for *_, stream_id in due:
            with self._lock:
                job = dict(self._jobs.get(stream_id) or {})
            if job:
                yield replace(self._acquire(stream_id, job), peak_viewers=_peak(job))

    def record_automation(
        self,
        stream_id: str,
        vod_id: str | None,
        status: str,
        retry_at: datetime | None = None,
        error: str | None = None,
    ) -> str:
        """Close or reschedule a job after the pipeline; returns its new state."""
        with self._lock:
            job = self._jobs.get(stream_id)
            if job is None:
                return "done"
            if status in {"completed", "skipped"}:
                self._finish_locked(stream_id, vod_id)
                outcome = "done"
            elif status == "waiting_gemini":
                # Only Gemini is missing (daily quota or overload).
                job["next_attempt_at"] = _iso(retry_at or self._clock() + timedelta(hours=1))
                job["last_error"] = error
                outcome = "waiting"
            else:
                outcome = "abandoned" if self._fail_locked(stream_id, error or status) else "retry"
            self._save_state()
        return outcome

    def run(
        self,
        on_cycle: Callable[[VODMonitoringCycle], None],
        stop_event: Event,
        max_cycles: int | None = None,
    ) -> None:
        def handle_monitoring_cycle(cycle: MonitoringCycle) -> None:
            on_cycle(VODMonitoringCycle(cycle, self.process_cycle(cycle)))

        self.monitor.run(handle_monitoring_cycle, stop_event, max_cycles=max_cycles)

    # ------------------------------------------------------------------
    # Acquisition of one job
    # ------------------------------------------------------------------

    def _acquire(self, stream_id: str, job: dict[str, Any]) -> VODAcquisitionResult:
        stream = LiveStream(**job["stream"])
        budget = self._budget(stream.broadcaster_login, int(job["clip_budget"]))
        vod_id = job.get("vod_id")
        if self._clock() - _parse(job["ended_at"]) > timedelta(seconds=MAX_JOB_AGE_SECONDS):
            error = "trop ancien : ses Shorts ne seraient plus publies"
            audio_path = find_downloaded_audio(self.input_dir, vod_id) if vod_id else None
            if audio_path is not None:
                audio_path.unlink(missing_ok=True)  # nothing left to do with it
            with self._lock:
                self._abandon_locked(stream_id, vod_id, error)
                self._save_state()
            return _result(stream, budget, "abandoned", vod_id=vod_id, error=error)
        try:
            if not vod_id:
                vod = self.api_client.find_vod_for_stream(stream.broadcaster_id, stream_id)
                if vod is None:
                    waited = self._clock() - _parse(job["ended_at"])
                    with self._lock:
                        if waited > timedelta(seconds=VOD_WAIT_SECONDS):
                            error = "aucune VOD publiee (desactivee ou supprimee par la chaine)"
                            self._abandon_locked(stream_id, None, error)
                            self._save_state()
                            return _result(stream, budget, "abandoned", error=error)
                        # A VOD normally appears right away: check again soon, without
                        # spending an attempt.
                        self._jobs[stream_id]["next_attempt_at"] = _iso(
                            self._clock() + timedelta(seconds=RETRY_BASE_SECONDS)
                        )
                        self._save_state()
                    return _result(stream, budget, "vod_not_available")
                vod_id = vod.vod_id
                with self._lock:
                    self._jobs[stream_id]["vod_id"] = vod_id
                    self._save_state()

            if vod_id in self._processed_vod_ids:
                with self._lock:
                    self._finish_locked(stream_id, vod_id)
                    self._save_state()
                return _result(stream, budget, "already_processed", vod_id=vod_id)

            audio_path = find_downloaded_audio(self.input_dir, vod_id)
            if audio_path is not None:
                return _result(stream, budget, "already_downloaded", vod_id=vod_id, downloaded_path=audio_path)

            self.input_dir.mkdir(parents=True, exist_ok=True)
            free = shutil.disk_usage(self.input_dir).free
            if free < MIN_FREE_BYTES:
                raise OSError(f"espace disque insuffisant ({free // 1024**2} Mo libres)")
            audio_path = self.downloader(f"https://www.twitch.tv/videos/{vod_id}", self.input_dir)
            return _result(stream, budget, "downloaded", vod_id=vod_id, downloaded_path=audio_path)
        except (TwitchAPIError, TwitchDownloadError, OSError, ValueError) as error:
            with self._lock:
                abandoned = stream_id in self._jobs and self._fail_locked(stream_id, str(error))
                self._save_state()
            return _result(
                stream, budget, "abandoned" if abandoned else "error", vod_id=vod_id, error=str(error)
            )

    # ------------------------------------------------------------------
    # Job state (call with the lock held)
    # ------------------------------------------------------------------

    def _fail_locked(self, stream_id: str, error: str) -> bool:
        """Count a failed attempt; return True when the job is abandoned."""
        job = self._jobs[stream_id]
        job["attempts"] = int(job.get("attempts", 0)) + 1
        job["last_error"] = error
        if job["attempts"] >= MAX_ATTEMPTS:
            self._abandon_locked(stream_id, job.get("vod_id"), error)
            return True
        delay = min(RETRY_BASE_SECONDS * 2 ** (job["attempts"] - 1), RETRY_MAX_SECONDS)
        job["next_attempt_at"] = _iso(self._clock() + timedelta(seconds=delay))
        return False

    def _priority(self, stream_id: str, job: dict[str, Any]) -> tuple[Any, ...]:
        """Top streamers first, then the highest peak viewers, then the oldest end."""
        budget = self._budget(job["stream"]["broadcaster_login"], int(job["clip_budget"]))
        return -budget, -_peak(job), job["ended_at"], stream_id

    def _started(self, job: dict[str, Any]) -> bool:
        vod_id = job.get("vod_id")
        return bool(vod_id) and find_downloaded_audio(self.input_dir, str(vod_id)) is not None

    def _purge_locked(self, now: datetime) -> None:
        """Drop the jobs no longer worth processing; the worker's cleanup deletes their files.

        Older than MAX_JOB_AGE_SECONDS, their Shorts would be stale; beyond the
        MAX_QUEUED_JOBS best ones, they would never be reached before that.
        """
        ranked = sorted(self._jobs.items(), key=lambda entry: self._priority(*entry))
        dropped = False
        for position, (stream_id, job) in enumerate(ranked):
            too_old = now - _parse(job["ended_at"]) > timedelta(seconds=MAX_JOB_AGE_SECONDS)
            if too_old or position >= MAX_QUEUED_JOBS:
                reason = (
                    "trop ancien : ses Shorts ne seraient plus publies" if too_old
                    else "file d'attente pleine : des VOD plus prioritaires passent avant"
                )
                self._abandon_locked(stream_id, job.get("vod_id"), reason)
                if job.get("vod_id"):  # its audio and any partial download (the worker cleans the rest)
                    for path in self.input_dir.glob(f"{job['vod_id']}_*"):
                        path.unlink(missing_ok=True)
                dropped = True
        if dropped:
            self._save_state()

    def _budget(self, login: str, budget: int) -> int:
        # Also applies to jobs queued before the streamer joined the list.
        if budget > 0 and login.lower() in self.top_streamers:
            return max(budget, TOP_STREAMER_CLIP_BUDGET)
        return budget

    def _abandon_locked(self, stream_id: str, vod_id: str | None, error: str) -> None:
        # Files are kept for inspection; the stream is never queued again.
        job = self._jobs.pop(stream_id, {})
        self._abandoned[stream_id] = {
            "vod_id": vod_id,
            "broadcaster_login": job.get("stream", {}).get("broadcaster_login", ""),
            "error": error,
            "abandoned_at": _iso(self._clock()),
        }
        self._remember_locked(stream_id, vod_id)

    def _finish_locked(self, stream_id: str, vod_id: str | None) -> None:
        self._jobs.pop(stream_id, None)
        self._remember_locked(stream_id, vod_id)

    def _remember_locked(self, stream_id: str, vod_id: str | None) -> None:
        self._processed_streams[stream_id] = vod_id or ""
        if vod_id:
            self._processed_vod_ids.add(vod_id)

    def _remember_processed(self, stream_id: str, vod_id: str) -> None:
        with self._lock:
            self._finish_locked(stream_id, vod_id)
            self._save_state()

    def _load_state(self) -> None:
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Unable to read Twitch VOD state: {error}") from error

        processed_streams = state.get("processed_streams", {})
        processed_vod_ids = state.get("processed_vod_ids", [])
        jobs = state.get("jobs", {})
        abandoned = state.get("abandoned", {})
        if (
            not isinstance(processed_streams, dict)
            or not isinstance(processed_vod_ids, list)
            or not isinstance(jobs, dict)
            or not isinstance(abandoned, dict)
        ):
            raise ValueError("Twitch VOD state has an invalid format.")
        try:
            for job in jobs.values():
                LiveStream(**job["stream"])
                _parse(job["ended_at"])
                _parse(job["next_attempt_at"])
                int(job["clip_budget"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"Twitch VOD state has an invalid job: {error}") from error
        self._processed_streams = {
            str(stream_id): str(vod_id or "")
            for stream_id, vod_id in processed_streams.items()
        }
        self._processed_vod_ids = set(processed_vod_ids) | {
            vod_id for vod_id in self._processed_streams.values() if vod_id
        }
        self._jobs = {str(stream_id): dict(job) for stream_id, job in jobs.items()}
        self._abandoned = dict(abandoned)

    def _save_state(self) -> None:
        # Only recent streams can end again: older memories are dropped, oldest first.
        for memory in (self._processed_streams, self._abandoned):
            for stream_id in list(memory)[: max(0, len(memory) - MEMORY_SIZE)]:
                del memory[stream_id]
        if len(self._processed_vod_ids) > MEMORY_SIZE:
            # Numeric ids: the longest, then the largest, are the most recent.
            self._processed_vod_ids = set(
                sorted(self._processed_vod_ids, key=lambda vod_id: (len(vod_id), vod_id))[-MEMORY_SIZE:]
            )
        state = {
            "processed_streams": self._processed_streams,
            "processed_vod_ids": sorted(self._processed_vod_ids),
            "jobs": self._jobs,
            "abandoned": self._abandoned,
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.state_path.with_name(f"{self.state_path.name}.tmp")
        temporary_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary_path.replace(self.state_path)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _peak(job: dict[str, Any]) -> int:
    # Jobs queued before peaks were recorded fall back to their last viewer count.
    return int(job.get("peak_viewers") or job["stream"].get("viewer_count") or 0)


def _result(
    stream: LiveStream,
    clip_budget: int,
    status: str,
    vod_id: str | None = None,
    downloaded_path: Path | None = None,
    error: str | None = None,
) -> VODAcquisitionResult:
    return VODAcquisitionResult(
        stream_id=stream.stream_id,
        clip_budget=clip_budget,
        status=status,
        broadcaster_id=stream.broadcaster_id,
        broadcaster_login=stream.broadcaster_login,
        broadcaster_name=stream.broadcaster_name,
        vod_id=vod_id,
        downloaded_path=downloaded_path,
        error=error,
        game_name=stream.game_name,
    )


def format_vod_acquisition_result(result: VODAcquisitionResult) -> str:
    name = result.broadcaster_name or result.stream_id
    if result.status == "queued":
        return f"Stream termine ajoute a la file : {name} (budget {result.clip_budget} clips)."
    if result.status == "downloaded":
        return f"Audio de la VOD {result.vod_id} telecharge : {result.downloaded_path}"
    if result.status == "vod_not_available":
        return f"VOD pas encore disponible pour {name}; nouvel essai dans quelques minutes."
    if result.status == "skipped_zero_budget":
        return f"Stream {result.stream_id} ignore : budget de clips nul."
    if result.status == "already_downloaded":
        return f"Audio de la VOD {result.vod_id} deja present : {result.downloaded_path}"
    if result.status == "already_processed":
        return f"VOD {result.vod_id or '?'} deja traitee pour le stream {result.stream_id}."
    if result.status == "abandoned":
        return f"VOD de {name} abandonnee (fichiers conserves) : {result.error}"
    return f"Erreur VOD pour {name} (nouvel essai plus tard) : {result.error}"
