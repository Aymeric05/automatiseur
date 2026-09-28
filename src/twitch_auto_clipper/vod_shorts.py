"""Shorts video generation from Gemini-selected VOD highlights."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
from typing import Any, Callable

from .candidate_clip import CandidateClipError, calculate_candidate_bounds
from .subtitles import SubtitleGenerationError, generate_ass_subtitles
from .video import get_video_duration
from .vod_highlights import VODHighlightSelectionResult


class ShortsGenerationError(RuntimeError):
    """Raised when a short cannot be generated from a selected highlight."""


# Extra source width (in pixels of the 1920px-high scaled frame) shown compared
# to the tight 1080px-wide centered crop used by ``framing.build_vertical_filter``.
ZOOM_OUT_EXTRA_WIDTH = 80
# YouTube Shorts accepts videos up to three minutes.
MAX_SHORT_DURATION = 180.0
SUCCESS_STATUSES = frozenset({"generated", "already_exists", "already_uploaded"})


@dataclass(frozen=True)
class VODShortResult:
    """Result for a single generated Short."""

    vod_id: str
    candidate_id: str
    source_path: Path
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


def _build_vertical_filter_zoomed_out(input_path: Path | None = None) -> str:
    """Build a centered 9:16 filter slightly wider than the tight crop.

    The source is scaled to 1920px high, then a centered window
    ``ZOOM_OUT_EXTRA_WIDTH`` pixels wider than the 1080px Shorts width is kept
    and scaled back down to fit 1080x1920. Small black bars fill the remaining
    height. No face/focus detection is used: a gameplay stream's facecam usually
    sits in a corner, and cropping on it would cut the game off the screen.
    """
    window = 1080 + ZOOM_OUT_EXTRA_WIDTH
    return (
        "scale=-2:1920,"
        f"crop='min(iw,{window})':ih,"
        "scale=1080:1920:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,"
        "setsar=1"
    )


def _subtitles_filter(subtitles_path: Path) -> str:
    subtitle_file = str(subtitles_path.resolve()).replace("\\", "/").replace(":", "\\:")
    return f"subtitles='{subtitle_file}'"


def _build_short_ffmpeg_command(
    source_path: Path,
    output_path: Path,
    start: float,
    end: float,
    vertical_filter: str,
    subtitles_path: Path | None = None,
) -> list[str]:
    """Return the FFmpeg command list for generating one vertical Short."""
    duration = end - start
    video_filter = vertical_filter
    if subtitles_path is not None:
        video_filter += "," + _subtitles_filter(subtitles_path)
    return [
        "ffmpeg",
        "-y",
        "-ss", str(start),
        "-i", str(source_path),
        "-t", str(duration),
        "-vf", video_filter,
        "-c:v", "libx264",
        "-c:a", "aac",
        "-movflags", "+faststart",
        "-f", "mp4",
        str(output_path),
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
        filter_builder: Callable[[Path], str] | None = None,
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
        source_path: Path,
        transcript_path: Path | None = None,
    ) -> VODShortsGenerationResult:
        """Generate one Short per selected highlight.

        Parameters
        ----------
        selection:
            The Gemini selection result produced by VODHighlightSelector.
        source_path:
            Path to the downloaded source VOD file.
        transcript_path:
            Optional transcript JSON with word timestamps, used to burn subtitles.
        """
        vod_id = selection.vod_id
        manifest_path = self.output_dir / f"{vod_id}_processing.json"

        if selection.status not in {"completed", "already_completed"}:
            raise ShortsGenerationError(
                f"La selection Gemini de {vod_id} n'est pas exploitable ({selection.status})."
            )
        if not _is_valid_output(source_path):
            raise ShortsGenerationError(
                f"Fichier source introuvable ou vide : {source_path}"
            )
        if not selection.selected:
            return VODShortsGenerationResult(vod_id, selection.clip_budget, (), "empty")

        self.output_dir.mkdir(parents=True, exist_ok=True)
        manifest = self._load_manifest(manifest_path)
        uploaded = manifest.get("youtube_uploads", {})
        if not isinstance(uploaded, dict):
            uploaded = {}

        vertical_filter = self._filter_builder(source_path)
        try:
            duration = float(self._duration_probe(source_path))
            if duration <= 0:
                raise ValueError("duree nulle")
        except Exception:
            duration = float("inf")  # FFmpeg stops at the end of the file anyway.
        segments = self._load_segments(transcript_path)

        shorts = [
            self._generate_one(
                vod_id=vod_id,
                item=item,
                source_path=source_path,
                clip_budget=selection.clip_budget,
                vertical_filter=vertical_filter,
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
        source_path: Path,
        clip_budget: int,
        vertical_filter: str,
        duration: float,
        segments: list[dict[str, Any]] | None,
        already_uploaded: dict[str, Any],
    ) -> VODShortResult:
        candidate_id = str(item.get("candidate_id", "unknown"))
        output_path = self.output_dir / f"{vod_id}_{candidate_id}_short.mp4"
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
                **extra,
            )

        try:
            start, end = self._clip_bounds(item, candidate_id, duration)
        except ShortsGenerationError as error:
            return result("error", error=str(error))

        if candidate_id in already_uploaded:
            # Uploaded Shorts are deleted locally: never regenerate them.
            return result("already_uploaded", start, end)
        if _is_valid_output(output_path):
            return result("already_exists", start, end)

        subtitles_path, warning = self._write_subtitles(segments, output_path, start, end)
        temporary_path = output_path.with_name(f"{output_path.stem}.tmp.mp4")
        try:
            temporary_path.unlink(missing_ok=True)
            command = _build_short_ffmpeg_command(
                source_path, temporary_path, start, end, vertical_filter, subtitles_path
            )
            self._ffmpeg_runner(command)
            if not _is_valid_output(temporary_path):
                raise ShortsGenerationError(
                    f"FFmpeg n'a produit aucune video valide pour {candidate_id}."
                )
            temporary_path.replace(output_path)
        except (ShortsGenerationError, subprocess.CalledProcessError, OSError) as error:
            self._remove_quietly(temporary_path)
            return result("error", start, end, error=str(error), warning=warning)
        finally:
            if subtitles_path is not None:
                self._remove_quietly(subtitles_path)

        return result(
            "generated", start, end, subtitles=subtitles_path is not None, warning=warning
        )

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
            subprocess.run(command, check=True, capture_output=True)
        except FileNotFoundError as error:
            raise ShortsGenerationError(
                "FFmpeg est introuvable dans le PATH."
            ) from error
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
                existing[short.candidate_id] = {
                    "file": short.output_path.name,
                    "start": short.start,
                    "end": short.end,
                    "candidate_start": short.candidate_start,
                    "candidate_end": short.candidate_end,
                    "gemini_score": short.gemini_score,
                    "gemini_justification": short.gemini_justification,
                }
                errors.pop(short.candidate_id, None)
            elif short.error:
                errors[short.candidate_id] = short.error
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
