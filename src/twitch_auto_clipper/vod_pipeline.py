"""End-to-end automation for one acquired Twitch VOD.

Order: transcription + chat -> heuristic candidates -> Gemini selection within
the clip budget -> Shorts generation -> metadata -> private YouTube upload.
Each stage is delegated to its existing module and is resumable on its own
(existing transcript/chat/selection/Shorts/uploads are reused), so running the
pipeline again only redoes the work that is missing.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .shorts_metadata import ShortMetadata, ShortMetadataError, build_short_metadata
from .shorts_upload import ShortUploadResult, VODShortsUploader, format_short_upload_result
from .vod_acquisition import VODAcquisitionResult
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
    ShortsGenerationError,
    VODShortsGenerationResult,
    VODShortsGenerator,
    format_vod_shorts_result,
)

READY_ACQUISITION_STATUSES = frozenset({"downloaded", "already_downloaded", "already_processed"})


@dataclass(frozen=True)
class VODAutomationResult:
    vod_id: str | None
    status: str  # "completed" | "partial" | "skipped" | "error"
    processing: VODProcessingResult | None = None
    selection: VODHighlightSelectionResult | None = None
    shorts: VODShortsGenerationResult | None = None
    metadata: tuple[tuple[str, ShortMetadata], ...] = ()
    uploads: tuple[ShortUploadResult, ...] = ()
    message: str | None = None


class VODAutomationPipeline:
    """Chain the existing VOD stages and stop as soon as a required one fails."""

    def __init__(
        self,
        processing_pipeline: VODProcessingPipeline | None = None,
        highlight_selector: VODHighlightSelector | None = None,
        shorts_generator: VODShortsGenerator | None = None,
        uploader: VODShortsUploader | None = None,
        output_dir: Path = Path("data/output"),
    ) -> None:
        self.output_dir = output_dir
        self.processing_pipeline = processing_pipeline or VODProcessingPipeline(output_dir)
        self.highlight_selector = highlight_selector or VODHighlightSelector(output_dir)
        self.shorts_generator = shorts_generator or VODShortsGenerator(output_dir)
        self.uploader = uploader  # None disables publication.

    def run(self, acquisition: VODAcquisitionResult) -> VODAutomationResult:
        result = self._run(acquisition)
        if result.processing is not None and result.vod_id:
            self._update_manifest(result.vod_id, {"automation_status": result.status})
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
            return VODAutomationResult(
                vod_id, "error", processing, selection,
                message=f"selection Gemini : {selection.error}",
            )
        if not selection.selected:
            return VODAutomationResult(
                vod_id, "completed", processing, selection,
                message="Aucun moment selectionne.",
            )

        # 4. Shorts generation.
        try:
            shorts = self.shorts_generator.generate(
                selection, source_path, processing.transcript_path
            )
        except (ShortsGenerationError, OSError) as error:
            return VODAutomationResult(
                vod_id, "error", processing, selection, message=f"Shorts : {error}"
            )

        # 5. Metadata from the clips' real transcript.
        segments = self._load_segments(processing.transcript_path)
        metadata: list[tuple[str, ShortMetadata]] = []
        metadata_errors: list[str] = []
        for short in shorts.shorts:
            if short.status not in {"generated", "already_exists"}:
                continue
            try:
                metadata.append((
                    short.candidate_id,
                    build_short_metadata(
                        broadcaster_name=processing.broadcaster_name,
                        broadcaster_login=processing.broadcaster_login,
                        vod_id=vod_id,
                        segments=segments,
                        clip_start=short.start,
                        clip_end=short.end,
                        candidate_start=short.candidate_start,
                        candidate_end=short.candidate_end,
                    ),
                ))
            except ShortMetadataError as error:
                metadata_errors.append(f"{short.candidate_id} : {error}")
        self._record_metadata(vod_id, metadata)

        # 6. Private YouTube publication, only for Shorts that are ready.
        uploads: list[ShortUploadResult] = []
        if self.uploader is not None:
            shorts_by_id = {short.candidate_id: short for short in shorts.shorts}
            for candidate_id, short_metadata in metadata:
                try:
                    uploads.append(
                        self.uploader.upload(vod_id, shorts_by_id[candidate_id], short_metadata)
                    )
                except (OSError, ValueError) as error:
                    uploads.append(ShortUploadResult(
                        candidate_id, shorts_by_id[candidate_id].output_path, "error",
                        error=str(error),
                    ))

        failed = (
            shorts.status != "completed"
            or bool(metadata_errors)
            or any(upload.status == "error" for upload in uploads)
        )
        return VODAutomationResult(
            vod_id,
            "partial" if failed else "completed",
            processing,
            selection,
            shorts,
            tuple(metadata),
            tuple(uploads),
            message="; ".join(f"metadonnees {error}" for error in metadata_errors) or None,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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
            for candidate_id, item in metadata:
                stored[candidate_id] = {"title": item.title, "description": item.description}
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


def find_unfinished_vods(output_dir: Path = Path("data/output")) -> list[VODAcquisitionResult]:
    """Rebuild acquisition results for VODs whose automation did not complete.

    VODs are marked as processed by the acquisition manager as soon as they are
    downloaded, so a failed Gemini call, FFmpeg run or upload would otherwise
    never be retried after a restart. Only VODs whose source file still exists
    and whose manifest has a positive clip budget are returned.
    """
    unfinished: list[VODAcquisitionResult] = []
    for manifest_path in sorted(output_dir.glob("*_processing.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(manifest, dict) or manifest.get("automation_status") == "completed":
            continue
        source = manifest.get("source_path")
        budget = manifest.get("clip_budget")
        vod_id = manifest.get("vod_id")
        if not source or not isinstance(budget, int) or budget <= 0 or not vod_id:
            continue
        source_path = Path(source)
        if not VODAutomationPipeline._is_valid_file(source_path):
            continue
        unfinished.append(VODAcquisitionResult(
            stream_id=str(manifest.get("stream_id", "")),
            clip_budget=budget,
            status="already_processed",
            broadcaster_id=str(manifest.get("broadcaster_id", "")),
            broadcaster_login=str(manifest.get("broadcaster_login", "")),
            broadcaster_name=str(manifest.get("broadcaster_name", "")),
            vod_id=str(vod_id),
            downloaded_path=source_path,
        ))
    return unfinished


def format_vod_automation_result(result: VODAutomationResult) -> list[str]:
    lines: list[str] = []
    if result.processing is not None:
        lines.extend(format_vod_processing_result(result.processing))
    if result.selection is not None:
        lines.append(format_vod_highlight_selection(result.selection))
    if result.shorts is not None:
        lines.extend(format_vod_shorts_result(result.shorts))
    for candidate_id, metadata in result.metadata:
        lines.append(f"  [titre] {candidate_id} : {metadata.title}")
    lines.extend(format_short_upload_result(upload) for upload in result.uploads)
    summary = f"Pipeline VOD {result.vod_id} : {result.status}"
    if result.message:
        summary += f" ({result.message})"
    lines.append(summary)
    return lines
