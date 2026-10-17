"""Shorts video generation from Gemini-selected VOD highlights."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
from typing import Any, Callable

from .candidate_clip import CandidateClipError, calculate_candidate_bounds
from .profanity import censor, profane_intervals
from .subtitles import SubtitleGenerationError, generate_ass_subtitles, render_hook_image
from .video import get_video_duration
from .vod_highlights import VODHighlightSelectionResult


class ShortsGenerationError(RuntimeError):
    """Raised when a short cannot be generated from a selected highlight."""


# Extra source width (in pixels of the 1920px-high scaled frame) shown compared
# to the tight 1080px-wide centered crop used by ``framing.build_vertical_filter``.
ZOOM_OUT_EXTRA_WIDTH = 140
# Top of the hook box, below the Shorts player's own top icons.
HOOK_TOP = 200
# Cold open: the Short opens on its strongest reaction (``peak``), then starts over.
COLD_OPEN_SECONDS = 1.5
COLD_OPEN_BEFORE = 0.5  # the teaser starts just before the peak, so the reaction is seen rising
COLD_OPEN_MIN_START = 4.0  # a peak in the first seconds is seen right away: no teaser
# YouTube Shorts accepts videos up to three minutes.
MAX_SHORT_DURATION = 180.0
# Reading a few seconds from Twitch and encoding them never takes this long.
FFMPEG_TIMEOUT_SECONDS = 1800
SUCCESS_STATUSES = frozenset({"generated", "already_exists", "already_uploaded"})

# A local video file, a stream URL, or a function returning one (called only
# when a Short actually has to be rendered).
VideoSource = Path | str | Callable[[], Path | str]


def clip_id(item: dict[str, Any]) -> str:
    """Stable identifier of a selected moment: its own start and end.

    Gemini's ``candidate_N`` numbers depend on the order of the candidate list,
    which changes when the transcript or the heuristic changes; files, the
    manifest and YouTube uploads are therefore keyed by the moment itself.
    """
    return f"{float(item['start']):.1f}-{float(item['end']):.1f}"


@dataclass(frozen=True)
class VODShortResult:
    """Result for a single generated Short."""

    vod_id: str
    candidate_id: str
    source_path: Path | str
    output_path: Path
    start: float
    end: float
    clip_budget: int
    gemini_score: float | None
    gemini_justification: str | None
    status: str  # "generated" | "already_exists" | "already_uploaded" | "error"
    error: str | None = None
    candidate_start: float | None = None
    candidate_end: float | None = None
    subtitles: bool = False
    warning: str | None = None
    clip_id: str | None = None
    description: str | None = None  # Gemini's teaser for the YouTube description
    muted: bool = False  # swear words were muted (and blurred in the subtitles)
    # Statistics only: where the moment comes from ("transcript", "chat" or "emotion"),
    # the emotion heard in it and its hook.
    source: str = "transcript"
    emotion: str | None = None
    hook: str | None = None
    focus_x: float | None = None  # where the crop is centered (0 to 1), None: the middle
    max_seconds: float | None = None  # the length cap of this moment (length test)
    cold_open: bool = False  # opens on its strongest reaction

    @property
    def key(self) -> str:
        """Manifest and upload key: the moment's ``clip_id`` when known."""
        return self.clip_id or self.candidate_id

    @property
    def succeeded(self) -> bool:
        return self.status in SUCCESS_STATUSES


@dataclass(frozen=True)
class VODShortsGenerationResult:
    """Aggregate result for all Shorts generated from one selection."""

    vod_id: str
    clip_budget: int
    shorts: tuple[VODShortResult, ...]
    status: str  # "completed" | "partial" | "failed" | "empty"

    @property
    def generated_count(self) -> int:
        return sum(1 for short in self.shorts if short.succeeded)

    @property
    def error_count(self) -> int:
        return sum(1 for short in self.shorts if short.status == "error")


def _build_vertical_filter_zoomed_out(input_path: Path | None = None, focus_x: float | None = None) -> str:
    """Build a 9:16 filter slightly wider than the tight crop.

    The source is scaled to 1920px high, then a window ``ZOOM_OUT_EXTRA_WIDTH``
    pixels wider than the 1080px Shorts width is kept and scaled back down to
    fit 1080x1920. Small black bars fill the remaining height. The window is
    centered on ``focus_x`` (0 to 1 of the width, see ``focus.find_focus``),
    else on the middle. Never on the streamer's face: a gameplay stream's
    facecam usually sits in a corner, and cropping on it would cut the game off.
    """
    window = 1080 + ZOOM_OUT_EXTRA_WIDTH
    position = (
        f":'max(0,min(iw-ow,{min(max(float(focus_x), 0.0), 1.0):.3f}*iw-ow/2))':0"
        if focus_x is not None
        else ""
    )
    return (
        "scale=-2:1920,"
        f"crop='min(iw,{window})':ih{position},"
        "scale=1080:1920:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,"
        "setsar=1"
    )


def _subtitles_filter(subtitles_path: Path) -> str:
    subtitle_file = str(subtitles_path.resolve()).replace("\\", "/").replace(":", "\\:")
    return f"subtitles='{subtitle_file}'"


def _build_short_ffmpeg_command(
    source_path: Path | str,
    output_path: Path,
    start: float,
    end: float,
    vertical_filter: str,
    subtitles_path: Path | None = None,
    hook_path: Path | None = None,
    mute: list[tuple[float, float]] | tuple[tuple[float, float], ...] = (),
    teaser: tuple[float, float] | None = None,
    teaser_mute: list[tuple[float, float]] | tuple[tuple[float, float], ...] = (),
) -> list[str]:
    """Return the FFmpeg command list for generating one vertical Short.

    ``mute`` lists the moments (seconds from ``start``) whose audio is silenced.
    ``teaser`` (start, end) is shown first, without subtitles (its swear words
    in ``teaser_mute``, seconds from its start), then the Short from ``start``.
    """
    if teaser is not None:
        return _build_cold_open_command(
            source_path, output_path, start, end, vertical_filter, subtitles_path, hook_path,
            mute, teaser, teaser_mute,
        )
    duration = end - start
    video_filter = vertical_filter
    if subtitles_path is not None:
        video_filter += "," + _subtitles_filter(subtitles_path)
    audio_filter = (
        "volume=0:enable='" + "+".join(f"between(t,{a},{b})" for a, b in mute) + "'"
        if mute
        else None
    )
    command = ["ffmpeg", "-y"]
    if str(source_path).startswith(("http://", "https://")):
        # Read the Twitch stream at its own pace (a few Mbit/s), not as fast as the
        # connection allows: a Short then takes about its duration to render.
        command += ["-readrate", "1"]
    command += ["-ss", str(start), "-i", str(source_path)]
    if hook_path is None:
        command += ["-t", str(duration), "-vf", video_filter]
        if audio_filter:
            command += ["-af", audio_filter]
    else:
        # The hook image stays on screen for the whole clip (overlay repeats its only frame).
        graph = f"[0:v]{video_filter}[base];[base][1:v]overlay=(W-w)/2:{HOOK_TOP}[v]"
        if audio_filter:
            graph += f";[0:a]{audio_filter}[a]"
        command += [
            "-i", str(hook_path),
            "-t", str(duration),
            "-filter_complex", graph,
            "-map", "[v]", "-map", "[a]" if audio_filter else "0:a?",
        ]
    return command + [
        "-c:v", "libx264",
        "-c:a", "aac",
        "-movflags", "+faststart",
        "-f", "mp4",
        str(output_path),
    ]


def _mute_filter(mute: list[tuple[float, float]] | tuple[tuple[float, float], ...]) -> str:
    return "volume=0:enable='" + "+".join(f"between(t,{a},{b})" for a, b in mute) + "'" if mute else "anull"


def _build_cold_open_command(
    source_path: Path | str,
    output_path: Path,
    start: float,
    end: float,
    vertical_filter: str,
    subtitles_path: Path | None,
    hook_path: Path | None,
    mute: list[tuple[float, float]] | tuple[tuple[float, float], ...],
    teaser: tuple[float, float],
    teaser_mute: list[tuple[float, float]] | tuple[tuple[float, float], ...],
) -> list[str]:
    """The Short preceded by its teaser: the same source read twice, then joined."""
    reading = ["-readrate", "1"] if str(source_path).startswith(("http://", "https://")) else []
    command = ["ffmpeg", "-y"]
    for segment_start, segment_end in (teaser, (start, end)):
        command += reading + ["-ss", str(segment_start), "-t", str(round(segment_end - segment_start, 3)),
                              "-i", str(source_path)]
    main_filter = vertical_filter + ("," + _subtitles_filter(subtitles_path) if subtitles_path else "")
    graph = (
        f"[0:v]{vertical_filter}[tv];[0:a]{_mute_filter(teaser_mute)}[ta];"
        f"[1:v]{main_filter}[mv];[1:a]{_mute_filter(mute)}[ma];"
        "[tv][ta][mv][ma]concat=n=2:v=1:a=1[cv][a]"
    )
    if hook_path is None:
        graph += ";[cv]null[v]"
    else:
        command += ["-i", str(hook_path)]
        graph += f";[cv][2:v]overlay=(W-w)/2:{HOOK_TOP}[v]"
    return command + [
        "-filter_complex", graph, "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart", "-f", "mp4", str(output_path),
    ]


def _is_valid_output(path: Path) -> bool:
    """Return True when a non-empty output file already exists."""
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _overall_status(shorts: list[VODShortResult]) -> str:
    if not shorts:
        return "empty"
    succeeded = sum(1 for short in shorts if short.succeeded)
    if succeeded == len(shorts):
        return "completed"
    if succeeded == 0:
        return "failed"
    return "partial"


class VODShortsGenerator:
    """Generate one vertical 9:16 MP4 per Gemini-selected highlight."""

    def __init__(
        self,
        output_dir: Path = Path("data/output"),
        ffmpeg_runner: Callable[[list[str]], None] | None = None,
        filter_builder: Callable[[Path, float | None], str] | None = None,
        duration_probe: Callable[[Path], float] | None = None,
        before: float = 0.5,  # candidates are sentence-aligned: keep a short breath only
        after: float = 1.0,
    ) -> None:
        self.output_dir = output_dir
        self._ffmpeg_runner = ffmpeg_runner or self._run_ffmpeg
        self._filter_builder = filter_builder or _build_vertical_filter_zoomed_out
        self._duration_probe = duration_probe or get_video_duration
        self.before = before
        self.after = after

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        selection: VODHighlightSelectionResult,
        source: VideoSource,
        transcript_path: Path | None = None,
    ) -> VODShortsGenerationResult:
        """Generate one Short per selected highlight.

        Parameters
        ----------
        selection:
            The Gemini selection result produced by VODHighlightSelector.
        source:
            The VOD video: a local file, a stream URL that FFmpeg reads only for
            the needed seconds, or a function returning one. A function is
            called only if a Short really has to be rendered.
        transcript_path:
            Optional transcript JSON with word timestamps, used to burn subtitles.
        """
        vod_id = selection.vod_id
        manifest_path = self.output_dir / f"{vod_id}_processing.json"

        if selection.status not in {"completed", "already_completed"}:
            raise ShortsGenerationError(
                f"La selection Gemini de {vod_id} n'est pas exploitable ({selection.status})."
            )
        if isinstance(source, Path) and not _is_valid_output(source):
            raise ShortsGenerationError(
                f"Fichier source introuvable ou vide : {source}"
            )
        if not selection.selected:
            return VODShortsGenerationResult(vod_id, selection.clip_budget, (), "empty")

        self.output_dir.mkdir(parents=True, exist_ok=True)
        manifest = self._load_manifest(manifest_path)
        uploaded = manifest.get("youtube_uploads", {})
        if not isinstance(uploaded, dict):
            uploaded = {}

        duration = float("inf")  # FFmpeg stops at the end of the VOD anyway.
        if isinstance(source, Path):
            try:
                duration = float(self._duration_probe(source))
                if duration <= 0:
                    raise ValueError("duree nulle")
            except Exception:
                duration = float("inf")
        segments = self._load_segments(transcript_path)

        resolved: list[Path | str] = []

        def resolve_source() -> Path | str:
            if not resolved:
                try:
                    resolved.append(source() if callable(source) else source)
                except Exception as error:  # e.g. Twitch unreachable: retried on the next run
                    raise ShortsGenerationError(f"Video de la VOD indisponible : {error}") from error
            return resolved[0]

        shorts = [
            self._generate_one(
                vod_id=vod_id,
                item=item,
                source=resolve_source,
                clip_budget=selection.clip_budget,
                duration=duration,
                segments=segments,
                already_uploaded=uploaded,
            )
            for item in selection.selected
        ]

        self._record_shorts(manifest_path, shorts)
        return VODShortsGenerationResult(
            vod_id=vod_id,
            clip_budget=selection.clip_budget,
            shorts=tuple(shorts),
            status=_overall_status(shorts),
        )

    # ------------------------------------------------------------------
    # Per-clip generation
    # ------------------------------------------------------------------

    def _generate_one(
        self,
        *,
        vod_id: str,
        item: dict[str, Any],
        source: Callable[[], Path | str],
        clip_budget: int,
        duration: float,
        segments: list[dict[str, Any]] | None,
        already_uploaded: dict[str, Any],
    ) -> VODShortResult:
        candidate_id = str(item.get("candidate_id", "unknown"))
        try:
            key: str | None = clip_id(item)
        except (KeyError, TypeError, ValueError):
            key = None  # invalid bounds: reported as an error below
        output_path = self.output_dir / f"{vod_id}_{key or candidate_id}_short.mp4"
        source_path: Path | str = ""
        # The highlighted sentence inside the candidate (falls back to the whole candidate).
        candidate_start = self._number(item.get("highlight_start", item.get("start")))
        candidate_end = self._number(item.get("highlight_end", item.get("end")))

        def result(status: str, start: float = 0.0, end: float = 0.0, **extra: Any) -> VODShortResult:
            return VODShortResult(
                vod_id=vod_id,
                candidate_id=candidate_id,
                source_path=source_path,
                output_path=output_path,
                start=start,
                end=end,
                clip_budget=clip_budget,
                gemini_score=item.get("gemini_score"),
                gemini_justification=item.get("gemini_justification"),
                status=status,
                candidate_start=candidate_start,
                candidate_end=candidate_end,
                clip_id=key,
                description=item.get("gemini_description"),
                source=str(item.get("source") or "transcript"),
                emotion=item.get("emotion"),
                hook=item.get("gemini_hook"),
                focus_x=self._number(item.get("focus_x")),
                max_seconds=self._number(item.get("max_seconds")),
                **extra,
            )

        try:
            start, end = self._clip_bounds(item, candidate_id, duration)
        except ShortsGenerationError as error:
            return result("error", error=str(error))

        if key in already_uploaded:
            # Uploaded Shorts are deleted locally: never regenerate them.
            return result("already_uploaded", start, end)
        if _is_valid_output(output_path):
            return result("already_exists", start, end)

        mute = profane_intervals(segments, start, end)
        teaser = self._cold_open(item, start, end)
        subtitles_path, warning = self._write_subtitles(segments, output_path, start, end)
        hook_path, hook_warning = self._write_hook(item.get("gemini_hook"), output_path)
        warning = "; ".join(filter(None, (warning, hook_warning))) or None
        temporary_path = output_path.with_name(f"{output_path.stem}.tmp.mp4")
        try:
            temporary_path.unlink(missing_ok=True)
            source_path = source()
            command = _build_short_ffmpeg_command(
                source_path, temporary_path, start, end,
                self._filter_builder(source_path, self._number(item.get("focus_x"))), subtitles_path, hook_path,
                mute=mute, teaser=teaser,
                teaser_mute=profane_intervals(segments, *teaser) if teaser else (),
            )
            self._ffmpeg_runner(command)
            if not _is_valid_output(temporary_path):
                raise ShortsGenerationError(
                    f"FFmpeg n'a produit aucune video valide pour {candidate_id}."
                )
            temporary_path.replace(output_path)
        except (ShortsGenerationError, subprocess.CalledProcessError, OSError, ValueError) as error:
            # ValueError/OSError also cover a VOD stream that cannot be resolved.
            self._remove_quietly(temporary_path)
            return result("error", start, end, error=str(error), warning=warning)
        finally:
            for path in (subtitles_path, hook_path):
                if path is not None:
                    self._remove_quietly(path)

        return result(
            "generated", start, end, subtitles=subtitles_path is not None, warning=warning,
            muted=bool(mute), cold_open=teaser is not None,
        )

    @classmethod
    def _cold_open(cls, item: dict[str, Any], start: float, end: float) -> tuple[float, float] | None:
        """The teaser shown first: from just before the moment's ``peak``, within the Short."""
        peak = cls._number(item.get("peak"))
        if peak is None or not start + COLD_OPEN_MIN_START <= peak < end:
            return None
        teaser_start = max(start, min(peak - COLD_OPEN_BEFORE, end - COLD_OPEN_SECONDS))
        return round(teaser_start, 3), round(teaser_start + COLD_OPEN_SECONDS, 3)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _clip_bounds(
        self, item: dict[str, Any], candidate_id: str, duration: float
    ) -> tuple[float, float]:
        """Pad the candidate with context and keep it within Shorts limits."""
        try:
            start, end = calculate_candidate_bounds(item, duration, self.before, self.after)
        except CandidateClipError as error:
            raise ShortsGenerationError(
                f"Intervalle invalide pour {candidate_id} : {error}"
            ) from error
        return round(start, 3), round(min(end, start + MAX_SHORT_DURATION), 3)

    @staticmethod
    def _write_subtitles(
        segments: list[dict[str, Any]] | None,
        output_path: Path,
        start: float,
        end: float,
    ) -> tuple[Path | None, str | None]:
        if not segments:
            return None, None
        subtitles_path = output_path.with_suffix(".ass")
        try:
            generate_ass_subtitles(segments, subtitles_path, clip_start=start, clip_end=end)
        except (SubtitleGenerationError, OSError) as error:
            return None, f"sous-titres ignores : {error}"
        return subtitles_path, None

    @staticmethod
    def _write_hook(hook: Any, output_path: Path) -> tuple[Path | None, str | None]:
        if not isinstance(hook, str) or not hook.strip():
            return None, None
        try:
            return render_hook_image(censor(hook), output_path.with_name(f"{output_path.stem}_hook.png")), None
        except (SubtitleGenerationError, OSError, ValueError) as error:
            return None, f"phrase d'accroche ignoree : {error}"

    @staticmethod
    def _load_segments(transcript_path: Path | None) -> list[dict[str, Any]] | None:
        if transcript_path is None:
            return None
        try:
            segments = json.loads(transcript_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return segments if isinstance(segments, list) else None

    @staticmethod
    def _number(value: Any) -> float | None:
        return float(value) if isinstance(value, (int, float)) else None

    @staticmethod
    def _remove_quietly(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    @staticmethod
    def _run_ffmpeg(command: list[str]) -> None:
        """Run an FFmpeg command, raising ShortsGenerationError on failure."""
        try:
            subprocess.run(command, check=True, capture_output=True, timeout=FFMPEG_TIMEOUT_SECONDS)
        except FileNotFoundError as error:
            raise ShortsGenerationError(
                "FFmpeg est introuvable dans le PATH."
            ) from error
        except subprocess.TimeoutExpired as error:
            raise ShortsGenerationError(f"FFmpeg interrompu apres {FFMPEG_TIMEOUT_SECONDS} s.") from error
        except subprocess.CalledProcessError as error:
            stderr = (error.stderr or b"").decode(errors="replace").strip()
            raise ShortsGenerationError(
                f"FFmpeg a echoue (code {error.returncode}) : {stderr[-500:]}"
            ) from error

    @staticmethod
    def _load_manifest(manifest_path: Path) -> dict[str, Any]:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return manifest if isinstance(manifest, dict) else {}

    def _record_shorts(
        self,
        manifest_path: Path,
        shorts: list[VODShortResult],
    ) -> None:
        """Record generated Shorts and their Gemini context in the VOD manifest."""
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            manifest = {}
        except (OSError, json.JSONDecodeError):
            return  # Non-fatal: skip manifest update if unreadable
        if not isinstance(manifest, dict):
            return

        existing = manifest.get("generated_shorts", {})
        if not isinstance(existing, dict):
            existing = {}
        errors = manifest.get("shorts_errors", {})
        if not isinstance(errors, dict):
            errors = {}
        for short in shorts:
            if short.succeeded:
                existing[short.key] = {
                    "candidate_id": short.candidate_id,
                    "file": short.output_path.name,
                    "start": short.start,
                    "end": short.end,
                    "candidate_start": short.candidate_start,
                    "candidate_end": short.candidate_end,
                    "gemini_score": short.gemini_score,
                    "gemini_justification": short.gemini_justification,
                    # Rendered with swear words muted and masked: only these are published.
                    "profanity_filtered": short.status == "generated"
                    or bool((existing.get(short.key) or {}).get("profanity_filtered")),
                    "muted": short.muted if short.status == "generated"
                    else bool((existing.get(short.key) or {}).get("muted")),
                    "source": short.source,
                    "emotion": short.emotion,
                    "hook": short.hook,
                    "focus_x": short.focus_x,
                    "max_seconds": short.max_seconds,
                    "cold_open": short.cold_open if short.status == "generated"
                    else bool((existing.get(short.key) or {}).get("cold_open")),
                }
                errors.pop(short.key, None)
            elif short.error:
                errors[short.key] = short.error
        manifest["generated_shorts"] = existing
        if errors:
            manifest["shorts_errors"] = errors
        else:
            manifest.pop("shorts_errors", None)

        tmp = manifest_path.with_name(f"{manifest_path.name}.tmp")
        try:
            tmp.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(manifest_path)
        except OSError:
            pass  # Non-fatal: manifest update failure does not abort the run


def format_vod_shorts_result(result: VODShortsGenerationResult) -> list[str]:
    """Return human-readable lines summarising the Shorts generation."""
    lines: list[str] = [
        f"Shorts {result.vod_id} : {result.generated_count}/{len(result.shorts)} "
        f"prets (budget {result.clip_budget}, status={result.status})"
    ]
    for short in result.shorts:
        if short.status == "error":
            lines.append(f"  [erreur] {short.candidate_id} : {short.error}")
        elif short.status == "already_uploaded":
            lines.append(f"  [deja publie] {short.candidate_id}")
        elif short.status == "already_exists":
            lines.append(
                f"  [deja present] {short.candidate_id} -> {short.output_path.name}"
            )
        else:
            lines.append(
                f"  [genere] {short.candidate_id} "
                f"({short.start:g}s-{short.end:g}s) -> {short.output_path.name}"
            )
        if short.warning:
            lines.append(f"    avertissement : {short.warning}")
    return lines
