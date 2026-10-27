"""End-to-end automation for one acquired Twitch VOD.

Order: transcription + chat -> heuristic candidates -> Gemini selection within
the clip budget -> Shorts generation -> metadata. Each stage is delegated to its
existing module and is resumable on its own (existing transcript/chat/selection/
Shorts are reused), so running the pipeline again only redoes the work that is
missing. Publication is separate: ``VODShortsUploader.publish_next`` uploads the
best Shorts of all completed VODs.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import json
import re
import statistics
from pathlib import Path
import shutil
import time
from typing import Any, Callable

from . import experiments
from .competitors import format_guide
from .focus import IRL_CATEGORIES, short_channel
from .highlights import EXCITEMENT_DB, _overlap_ratio, expand_moment, split_sentences
from .trimming import snap_ends
from .profanity import has_slur
from .video import audio_levels
from .shorts_metadata import ShortMetadata, ShortMetadataError, build_short_metadata, clip_transcript_text
from .vod_acquisition import (
    MAX_ATTEMPTS,
    TwitchVODAcquisitionManager,
    VODAcquisitionResult,
    format_vod_acquisition_result,
)
from .vod_highlights import (
    VODHighlightSelectionResult,
    VODHighlightSelector,
    format_vod_highlight_selection,
)
from .vod_processing import (
    VODProcessingPipeline,
    VODProcessingResult,
    format_vod_processing_result,
)
from .vod_shorts import (
    COLD_OPEN_MIN_START,
    ShortsGenerationError,
    clip_id,
    VODShortsGenerationResult,
    VODShortsGenerator,
    format_vod_shorts_result,
)

READY_ACQUISITION_STATUSES = frozenset({"downloaded", "already_downloaded", "already_processed"})
# Gemini answers 429 when the project's quota is used up (the free tier allows
# 20 requests a day) and 503 when the model is overloaded: the VOD then waits,
# without counting a failed attempt, instead of being abandoned.
GEMINI_WAIT = timedelta(minutes=30)
# Asked for many moments, Gemini calls almost everything "interesting": below
# this score (0-100) a moment is neither rendered nor published.
MIN_GEMINI_SCORE = 60
# A Short whose picture is still in more than this share of its frames is never rendered.
MAX_STILL_SHARE = 0.5
# Where in each Short (share of its length) Gemini looks to frame it.
FOCUS_SAMPLES = (0.2, 0.5, 0.8)
LEAD_IN_ANALYSIS_SECONDS = 20  # audio examined before a moment to find what triggers it
MAX_SHORT_OVERLAP = 0.3  # widened moments sharing more of the shorter one are near-duplicates
# A temporary file untouched this long belongs to a run cut short (closed window, sleep,
# crash): a live download, render or transcription rewrites its files every few minutes.
STALE_TEMP_SECONDS = 6 * 3600
# ".temp.": the audio conversion yt-dlp leaves behind when the app is closed during it.
TEMP_MARKERS = (".tmp", ".temp.", ".part", ".ytdl", "_hook.png", ".ass")
GEMINI_UNAVAILABLE_MARKERS = ("429", "resource_exhausted", "exceeded", "quota", "503", "unavailable", "high demand")


def _gemini_retry_at(message: str | None) -> datetime | None:
    """When to try Gemini again, or None if the error is not about its availability."""
    text = (message or "").lower()
    if not any(marker in text for marker in GEMINI_UNAVAILABLE_MARKERS):
        return None
    delay = re.search(r"retrydelay['\"]?\s*:\s*['\"]?(\d+)s", text)  # given by Google with a 429
    wait = timedelta(seconds=int(delay.group(1)) + 60) if delay else GEMINI_WAIT
    return datetime.now(timezone.utc) + wait


@dataclass(frozen=True)
class VODAutomationResult:
    vod_id: str | None
    status: str  # "completed" | "waiting_gemini" | "partial" | "skipped" | "error"
    processing: VODProcessingResult | None = None
    selection: VODHighlightSelectionResult | None = None
    shorts: VODShortsGenerationResult | None = None
    metadata: tuple[tuple[str, ShortMetadata], ...] = ()
    message: str | None = None
    retry_at: datetime | None = None  # waiting_gemini: when Gemini should be back


class VODAutomationPipeline:
    """Chain the existing VOD stages and stop as soon as a required one fails.

    ``acquisition.downloaded_path`` is what gets transcribed (the VOD audio or a
    full video). ``video_source`` gives the video the Shorts are cut from (by
    default that same file); it is only called when a Short must be rendered.
    With ``delete_sources_on_success``, the downloaded audio and the chat files
    are deleted once the VOD is completed; transcript, selection, manifest and
    Shorts are kept (Shorts until they are published or too old).
    With ``delete_sources_on_success``, the transcript and selections go too:
    only the Shorts and the manifest stay.
    """

    def __init__(
        self,
        processing_pipeline: VODProcessingPipeline | None = None,
        highlight_selector: VODHighlightSelector | None = None,
        shorts_generator: VODShortsGenerator | None = None,
        output_dir: Path = Path("data/output"),
        video_source: Callable[[VODAcquisitionResult], Path | str] | None = None,
        delete_sources_on_success: bool = False,
        focus_finder: Callable[[str, list[float]], list[dict[str, Any]]] | None = None,
        moment_trimmer: Callable[..., list[dict[str, Any] | None]] | None = None,
        reserve_gate: Callable[[dict[str, Any], str, str, int], bool] | None = None,
        still_checker: Callable[[str, float, float, float | None], float] | None = None,
        speaker_finder: Callable[[Path, list[dict[str, Any]], list[dict[str, Any]]], list[list[list[float]]]] | None = None,
    ) -> None:
        self.output_dir = output_dir
        self.processing_pipeline = processing_pipeline or VODProcessingPipeline(output_dir)
        self.highlight_selector = highlight_selector or VODHighlightSelector(output_dir)
        self.shorts_generator = shorts_generator or VODShortsGenerator(output_dir)
        self.video_source = video_source
        self.delete_sources_on_success = delete_sources_on_success
        # Where to center each Short of a screen-sharing stream (see focus.find_focus).
        self.focus_finder = focus_finder
        # Gemini's start and end of each Short (see trimming.trim_moments); None: heuristic bounds.
        self.moment_trimmer = moment_trimmer
        # Whether a moment can enter its channel's reserve (item, login, vod_id, budget):
        # one that would be deleted right away is never rendered.
        self.reserve_gate = reserve_gate
        # Share of a Short's frames that do not move (see focus.still_share); None: not checked.
        self.still_checker = still_checker
        # Per moment, the spans said by a watched video or game: left out of the subtitles
        # (see speakers.media_speech); None: every word is subtitled.
        self.speaker_finder = speaker_finder

    def run(self, acquisition: VODAcquisitionResult) -> VODAutomationResult:
        result = self._run(acquisition)
        if result.processing is not None and result.vod_id:
            update: dict[str, Any] = {"automation_status": result.status}
            if result.status == "completed" and self.delete_sources_on_success:
                update["deleted_sources"] = self._delete_sources(acquisition.downloaded_path, result.processing)
            self._update_manifest(result.vod_id, update)
        return result

    def _run(self, acquisition: VODAcquisitionResult) -> VODAutomationResult:
        vod_id = acquisition.vod_id
        source_path = acquisition.downloaded_path
        if (
            acquisition.status not in READY_ACQUISITION_STATUSES
            or vod_id is None
            or source_path is None
            or not self._is_valid_file(source_path)
        ):
            return VODAutomationResult(vod_id, "skipped", message="VOD absente ou invalide.")
        if acquisition.clip_budget <= 0:
            return VODAutomationResult(vod_id, "skipped", message="Budget de clips nul.")

        # 1. Transcription and chat.
        try:
            processing = self.processing_pipeline.process(acquisition)
        except (OSError, ValueError) as error:
            return VODAutomationResult(vod_id, "error", message=f"traitement VOD : {error}")
        if processing.transcription_status == "error":
            return VODAutomationResult(
                vod_id, "error", processing,
                message="Transcription indisponible : selection et Shorts ignores.",
            )

        # 2-3. Candidates and Gemini selection (budget handled by the selector).
        try:
            selection = self.highlight_selector.select(processing)
        except Exception as error:
            return VODAutomationResult(vod_id, "error", processing, message=f"selection : {error}")
        if selection.status == "error":
            retry_at = selection.retry_at or _gemini_retry_at(selection.error)
            if retry_at is not None:
                return VODAutomationResult(
                    vod_id, "waiting_gemini", processing, selection,
                    message=f"Gemini indisponible (quota ou surcharge) : {selection.error}",
                    retry_at=retry_at,
                )
            return VODAutomationResult(
                vod_id, "error", processing, selection,
                message=f"selection Gemini : {selection.error}",
            )
        # Only the moments Gemini found worth a Short are rendered and published;
        # a moment with a slur is dropped (swear words are only muted).
        segments = self._load_segments(processing.transcript_path)

        def has_slurs(item: dict[str, Any]) -> bool:
            start, end = float(item.get("start", 0)), float(item.get("end", 0))
            spoken = clip_transcript_text(segments, start - 1.0, end + 2.0)  # with the render margins
            return has_slur(spoken) or has_slur(str(item.get("gemini_hook") or ""))

        sentences = split_sentences(segments)

        def with_context(item: dict[str, Any]) -> dict[str, Any]:
            """The moment with what triggers it before and the full reaction after."""
            start, end = float(item.get("start", 0)), float(item.get("end", 0))
            window = int(min(LEAD_IN_ANALYSIS_SECONDS, start))
            try:
                levels = audio_levels(source_path, start - window, window) if window >= 1 else []
            except Exception:  # unreadable audio: a fixed lead-in is used
                levels = []
            new_start, new_end = expand_moment(start, end, sentences, levels)
            # The highlighted sentence (title quote) stays the original moment.
            return {
                **item, "start": new_start, "end": new_end,
                "highlight_start": item.get("highlight_start", start),
                "highlight_end": item.get("highlight_end", end),
                "peak": reaction_peak(item, source_path, new_start, new_end),
            }

        widened = [
            with_context(item) for item in selection.selected
            if item.get("gemini_interesting", True) is not False
            and float(item.get("gemini_score", MIN_GEMINI_SCORE)) >= MIN_GEMINI_SCORE
        ]
        selection = replace(selection, selected=tuple(
            without_near_duplicates([moment for moment in widened if not has_slurs(moment)])
        ))
        if not selection.selected:
            return VODAutomationResult(
                vod_id, "completed", processing, selection,
                message="Aucun moment assez interessant pour un Short.",
            )

        # How many moments each step keeps, logged for the daily optimization loop.
        funnel = [f"{len(selection.selected)} retenus"]
        # A/B tests running on this VOD's likely channel (see experiments.py).
        test_variants, test_settings = experiments.for_vod(vod_id, short_channel(None, processing.game_name))
        if self.moment_trimmer is not None:
            guide = dict(format_guide(self.output_dir, short_channel(None, processing.game_name)))
            guide["rules"] = list(guide.get("rules", [])) + list(test_settings.get("trim_rules", []))
            if test_settings.get("ideal_seconds"):
                guide["ideal_seconds"] = test_settings["ideal_seconds"]
            selection = replace(selection, selected=self._trimmed(
                selection.selected, sentences, source_path, processing.broadcaster_name, guide,
            ))
            funnel.append(f"{len(selection.selected)} complets")
            if not selection.selected:
                return VODAutomationResult(
                    vod_id, "completed", processing, selection,
                    message="Aucun moment comprehensible seul pour un Short.",
                )

        if self.focus_finder is not None and processing.game_name.lower() not in IRL_CATEGORIES:
            selection = replace(selection, selected=self._with_focus(vod_id, selection.selected))
        # Video games go to one YouTube channel, everything else to the other.
        selection = replace(selection, selected=tuple(
            {
                **moment, "channel": short_channel(moment.get("gaming"), processing.game_name),
                "experiments": test_variants, "cold_open_off": test_settings.get("cold_open") is False,
            }
            for moment in selection.selected
        ))
        if self.reserve_gate is not None:
            selection = replace(selection, selected=tuple(
                moment for moment in selection.selected
                if self.reserve_gate(moment, processing.broadcaster_login, vod_id, processing.clip_budget)
            ))
            funnel.append(f"{len(selection.selected)} admis en reserve")
            if not selection.selected:
                return VODAutomationResult(
                    vod_id, "completed", processing, selection,
                    message="Aucun moment assez bon pour entrer dans une reserve.",
                )
        if self.still_checker is not None:
            selection = replace(selection, selected=tuple(
                moment for moment in selection.selected if not self._frozen(vod_id, moment)
            ))
            funnel.append(f"{len(selection.selected)} avec du mouvement")
            if not selection.selected:
                return VODAutomationResult(
                    vod_id, "completed", processing, selection, message="Aucun moment avec du mouvement a l'image.",
                )
        if self.speaker_finder is not None:
            try:
                spans = self.speaker_finder(source_path, list(selection.selected), sentences)
            except Exception:  # Gemini unavailable: every word is subtitled, as before
                spans = None
            if spans:
                selection = replace(selection, selected=tuple(
                    {**moment, "media_speech": media} for moment, media in zip(selection.selected, spans)
                ))

        # 4. Shorts generation.
        video_source = self.video_source
        source: Any = (lambda: video_source(acquisition)) if video_source else source_path
        try:
            shorts = self.shorts_generator.generate(
                selection, source, processing.transcript_path
            )
        except (ShortsGenerationError, OSError) as error:
            return VODAutomationResult(
                vod_id, "error", processing, selection, message=f"Shorts : {error}"
            )

        # 5. Metadata from the clips' real transcript (titles written by Gemini).
        titles = {clip_id(item): item.get("gemini_title") for item in selection.selected}
        metadata: list[tuple[str, ShortMetadata]] = []
        metadata_errors: list[str] = []
        for short in shorts.shorts:
            if short.status not in {"generated", "already_exists"}:
                continue
            try:
                metadata.append((
                    short.key,
                    build_short_metadata(
                        broadcaster_name=processing.broadcaster_name,
                        broadcaster_login=processing.broadcaster_login,
                        vod_id=vod_id,
                        segments=segments,
                        clip_start=short.start,
                        clip_end=short.end,
                        candidate_start=short.candidate_start,
                        candidate_end=short.candidate_end,
                        game_name=processing.game_name,
                        teaser=short.description,
                        title=titles.get(short.key),
                    ),
                ))
            except ShortMetadataError as error:
                metadata_errors.append(f"{short.key} : {error}")
        self._record_metadata(vod_id, metadata)

        failed = shorts.status != "completed" or bool(metadata_errors)
        return VODAutomationResult(
            vod_id,
            "partial" if failed else "completed",  # completed: the Shorts can be published
            processing,
            selection,
            shorts,
            tuple(metadata),
            message="; ".join(["entonnoir : " + ", ".join(funnel)] + [f"metadonnees {error}" for error in metadata_errors]),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _trimmed(
        self, moments: tuple[dict[str, Any], ...], sentences: list[dict[str, Any]], source_path: Path, streamer: str,
        guide: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """The moments with Gemini's bounds; one it finds incomplete is dropped (never rendered)."""
        try:
            trims = self.moment_trimmer(list(moments), sentences, streamer, guide)
        except Exception:  # Gemini unavailable: still snap ends to a sentence boundary
            return tuple(snap_ends(list(moments), sentences))
        kept = []
        for moment, trim in zip(moments, trims):
            if trim is None:
                continue
            if trim:
                moment = {**moment, **trim, "trimmed": True}
                # trim may only carry a snapped "end" (fallback): use the merged moment's
                # own bounds, never trim's, which can lack "start" and crash the VOD.
                moment["peak"] = reaction_peak(moment, source_path, moment["start"], moment["end"])
            kept.append(moment)
        return tuple(without_near_duplicates(kept))

    def _frozen(self, vod_id: str, moment: dict[str, Any]) -> bool:
        """Whether the Short's picture barely moves (a menu, a still picture): never rendered."""
        try:
            share = self.still_checker(vod_id, float(moment["start"]), float(moment["end"]), moment.get("focus_x"))
        except Exception:  # Twitch unavailable: the moment is kept, as before
            return False
        return share > MAX_STILL_SHARE

    def _with_focus(self, vod_id: str, moments: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
        """The moments with where to center their Short (``focus_x``) and whether they show
        a video game (``gaming``); unchanged when unknown.

        Gemini sees FOCUS_SAMPLES frames spread over each Short's final bounds: the
        Short follows what most of them show (the median center of the screen
        frames, or centered when most are camera shots), not a single instant.
        """
        times = [
            float(moment["start"]) + share * (float(moment["end"]) - float(moment["start"]))
            for moment in moments for share in FOCUS_SAMPLES
        ]
        try:
            found = self.focus_finder(vod_id, times)
        except Exception:  # Twitch or Gemini unavailable: centered Shorts, as before
            return moments
        focused = []
        for index, moment in enumerate(moments):
            frames = found[index * len(FOCUS_SAMPLES):(index + 1) * len(FOCUS_SAMPLES)]
            info: dict[str, Any] = {}
            centers = [frame["focus_x"] for frame in frames if "focus_x" in frame]
            if len(centers) * 2 > len(frames):  # mostly a shared screen
                info["focus_x"] = round(statistics.median(centers), 3)
            cams = [frame["facecam"] for frame in frames if "facecam" in frame]
            if "focus_x" in info and len(cams) * 2 > len(frames):  # the webcam over a shared screen
                info["facecam"] = [round(statistics.median(cam[i] for cam in cams), 3) for i in range(4)]
            votes = [frame["gaming"] for frame in frames if "gaming" in frame]
            if votes:
                info["gaming"] = votes.count(True) * 2 > len(votes)
            focused.append({**moment, **info})
        return tuple(focused)

    def _delete_sources(self, source_path: Path, processing: VODProcessingResult) -> list[str]:
        """Delete everything a completed VOD no longer needs.

        Only its Shorts and its manifest (which holds their titles and
        descriptions) stay, until the Shorts are published or discarded.
        """
        vod_id = processing.vod_id
        candidates = [
            processing.chat_path,
            processing.timestamped_chat_path,
            processing.transcript_path,
            *self.output_dir.glob(f"{vod_id}_highlights.json"),
            *self.output_dir.glob(f"{vod_id}_emotions.json"),
            *self.output_dir.glob(f"{vod_id}_gemini_selection_*.json"),
        ]
        if "_audio." in source_path.name:  # never a full video the user put there
            # The audio and any leftover of an interrupted download.
            candidates += source_path.parent.glob(f"{vod_id}_audio*")
        deleted = []
        for path in candidates:
            try:
                if path.is_file():
                    path.unlink()
                    deleted.append(path.name)
            except OSError:
                pass  # e.g. opened elsewhere on Windows: kept, nothing else depends on it
        return deleted

    @staticmethod
    def _is_valid_file(path: Path) -> bool:
        try:
            return path.is_file() and path.stat().st_size > 0
        except OSError:
            return False

    @staticmethod
    def _load_segments(path: Path) -> list[dict[str, Any]]:
        try:
            segments = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return segments if isinstance(segments, list) else []

    def _record_metadata(
        self, vod_id: str, metadata: list[tuple[str, ShortMetadata]]
    ) -> None:
        if not metadata:
            return

        def merge(manifest: dict[str, Any]) -> None:
            stored = manifest.get("shorts_metadata")
            if not isinstance(stored, dict):
                stored = {}
            for key, item in metadata:
                stored[key] = {"title": item.title, "description": item.description}
            manifest["shorts_metadata"] = stored

        self._update_manifest(vod_id, merge)

    def _update_manifest(self, vod_id: str, change: Any) -> None:
        manifest_path = self.output_dir / f"{vod_id}_processing.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(manifest, dict):
            return
        if callable(change):
            change(manifest)
        else:
            manifest.update(change)
        temporary_path = manifest_path.with_name(f"{manifest_path.name}.tmp")
        try:
            temporary_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary_path.replace(manifest_path)
        except OSError:
            pass


def reaction_peak(item: dict[str, Any], source_path: Path, start: float, end: float) -> float | None:
    """When the strongest reaction is heard (the Short's cold open), None when nothing stands out.

    The laugh or scream found in the audio, else the loudest second, at
    least ``EXCITEMENT_DB`` above the clip's usual level.
    """
    onset = item.get("onset")
    if isinstance(onset, (int, float)) and start + COLD_OPEN_MIN_START <= onset < end:
        return float(onset)
    try:
        levels = audio_levels(source_path, start, int(end - start))
    except Exception:
        return None
    later = levels[int(COLD_OPEN_MIN_START):]
    if not later or max(later) < sorted(levels)[len(levels) // 2] + EXCITEMENT_DB:
        return None
    return round(start + COLD_OPEN_MIN_START + later.index(max(later)), 2)


def without_near_duplicates(moments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Best moments first; one sharing more than MAX_SHORT_OVERLAP with a better one is dropped.

    Widened moments (set-up before, full reaction after) of the same live can
    cover the same scene: only the best Short of it is kept.
    """
    kept: list[dict[str, Any]] = []
    for moment in sorted(moments, key=lambda item: -float(item.get("gemini_score") or 0)):
        if all(_overlap_ratio(moment, other) <= MAX_SHORT_OVERLAP for other in kept):
            kept.append(moment)
    return kept


def cleanup_finished_vods(input_dir: Path, output_dir: Path, active_vod_ids: set[str]) -> list[str]:
    """Delete every file of the VODs that are done, and stale temporary files; returns the VOD ids.

    Temporary files (partial downloads, cut renders, transcription chunks,
    chat cache) untouched for ``STALE_TEMP_SECONDS`` are deleted whatever their VOD.

    A VOD is done when no job is left for it and none of its Shorts is in the
    reserve (Shorts of a completed VOD; the publisher keeps the reserve to its
    best ones, so an abandoned or failed VOD's Shorts are never kept). Its
    audio, chat, transcript, selections and manifest then go too: the Twitch
    VOD state still records it, so it is never processed again. Only files
    named after a VOD id (digits) are touched.
    """
    stale_before = time.time() - STALE_TEMP_SECONDS
    leftovers = [
        path
        for directory in (input_dir, output_dir)
        for path in directory.glob("*")
        if path.name.split("_", 1)[0].isdigit()  # the app's own files only, never the user's
        and any(marker in path.name for marker in TEMP_MARKERS)
    ]
    leftovers += list((output_dir / "tmp").glob("*"))  # transcription chunks, chat download cache
    for path in leftovers:
        try:
            if path.stat().st_mtime < stale_before:
                shutil.rmtree(path) if path.is_dir() else path.unlink()
        except OSError:
            pass  # in use or already gone: tried again next time

    files: dict[str, list[Path]] = {}
    for directory in (input_dir, output_dir):
        for path in directory.glob("*_*"):
            vod_id = path.name.split("_", 1)[0]
            if vod_id.isdigit() and path.is_file():
                files.setdefault(vod_id, []).append(path)
    done = []
    for vod_id, paths in files.items():
        if vod_id in active_vod_ids:
            continue
        if any(path.name.endswith("_short.mp4") for path in paths):
            try:
                manifest = json.loads((output_dir / f"{vod_id}_processing.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                manifest = None
            if isinstance(manifest, dict) and manifest.get("automation_status") == "completed":
                continue  # its Shorts are in the reserve
        for path in paths:
            try:
                path.unlink()
            except OSError:
                pass  # e.g. opened elsewhere on Windows: tried again next time
        done.append(vod_id)
    return done


def process_due_vods(
    manager: TwitchVODAcquisitionManager,
    automation: VODAutomationPipeline,
    report: Callable[[str, bool], None],
    download: bool = True,
) -> int:
    """Acquire and process every due VOD job once; returns how many were due.

    With ``download=False``, only the VODs already downloaded (by the prefetch
    thread) are processed.

    Runs on the worker side, never in the monitoring loop. ``report`` receives
    each line and whether it is an error. The files of finished VODs are
    deleted before and after each job.
    """

    def cleanup() -> None:
        done = cleanup_finished_vods(manager.input_dir, automation.output_dir, manager.active_vod_ids())
        if done:
            report(f"Fichiers supprimes (VOD terminees) : {', '.join(sorted(done))}", False)

    cleanup()
    count = 0
    for acquisition in manager.acquire_due(download):
        count += 1
        report(format_vod_acquisition_result(acquisition), acquisition.status in {"error", "abandoned"})
        if acquisition.status not in {"downloaded", "already_downloaded"}:
            continue  # already rescheduled or closed by the manager
        try:
            result = automation.run(acquisition)
        except Exception as error:  # an unexpected bug must not stop the worker
            result = VODAutomationResult(acquisition.vod_id, "error", message=f"erreur inattendue : {error!r}")
        for line in format_vod_automation_result(result):
            report(line, result.status in {"error", "partial"})
        outcome = manager.record_automation(
            acquisition.stream_id, acquisition.vod_id, result.status,
            retry_at=result.retry_at, error=result.message,
        )
        if outcome == "abandoned":
            report(f"VOD {acquisition.vod_id} abandonnee apres {MAX_ATTEMPTS} echecs (fichiers conserves).", True)
        elif outcome == "retry":
            report(f"VOD {acquisition.vod_id} : nouvel essai automatique plus tard.", True)
        elif outcome == "waiting":
            report(
                f"VOD {acquisition.vod_id} : Gemini indisponible, nouvel essai apres "
                f"{result.retry_at:%Y-%m-%d %H:%M} UTC.", True,
            )
        cleanup()
    return count


def format_vod_automation_result(result: VODAutomationResult) -> list[str]:
    lines: list[str] = []
    if result.processing is not None:
        lines.extend(format_vod_processing_result(result.processing))
    if result.selection is not None:
        lines.append(format_vod_highlight_selection(result.selection))
    if result.shorts is not None:
        lines.extend(format_vod_shorts_result(result.shorts))
    for key, metadata in result.metadata:
        lines.append(f"  [titre] {key} : {metadata.title}")
    summary = f"Pipeline VOD {result.vod_id} : {result.status}"
    if result.message:
        summary += f" ({result.message})"
    lines.append(summary)
    return lines
