"""Publish generated Shorts to YouTube and clean up confirmed uploads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable

from .shorts_metadata import ShortMetadata
from .vod_shorts import VODShortResult
from .youtube import upload_video

UPLOAD_PRIVACY = "private"


@dataclass(frozen=True)
class ShortUploadResult:
    candidate_id: str
    output_path: Path
    status: str  # "uploaded" | "already_uploaded" | "skipped" | "error"
    video_id: str | None = None
    url: str | None = None
    title: str | None = None
    local_file_deleted: bool = False
    error: str | None = None


class VODShortsUploader:
    """Upload each generated Short once, privately, then delete the local copy.

    The local video is removed only after YouTube returned a video ID and that
    ID has been saved in the VOD manifest. Any failure, exception or
    interruption leaves the local file in place so it can be retried.
    Only the Short itself is deleted: never the source VOD, the transcript,
    the chat files or the manifests.
    """

    def __init__(
        self,
        output_dir: Path = Path("data/output"),
        uploader: Callable[..., tuple[str, str]] | None = None,
        client_secrets_path: Path = Path("credentials.json"),
        token_path: Path = Path("youtube-token.json"),
        expected_channel_id: str | None = None,
        delete_after_upload: bool = True,
    ) -> None:
        self.output_dir = output_dir
        self._uploader = uploader or upload_video
        self.client_secrets_path = client_secrets_path
        self.token_path = token_path
        self.expected_channel_id = expected_channel_id
        self.delete_after_upload = delete_after_upload

    def upload(
        self,
        vod_id: str,
        short: VODShortResult,
        metadata: ShortMetadata,
    ) -> ShortUploadResult:
        manifest_path = self.output_dir / f"{vod_id}_processing.json"
        manifest = self._load_manifest(manifest_path)
        uploads = manifest.get("youtube_uploads", {})
        if isinstance(uploads, dict) and short.candidate_id in uploads:
            previous = uploads[short.candidate_id]
            self._delete_local(short.output_path)
            return ShortUploadResult(
                short.candidate_id,
                short.output_path,
                "already_uploaded",
                video_id=previous.get("video_id") if isinstance(previous, dict) else None,
                url=previous.get("url") if isinstance(previous, dict) else None,
            )
        if short.status not in {"generated", "already_exists"}:
            return ShortUploadResult(
                short.candidate_id, short.output_path, "skipped",
                error=f"Short non disponible ({short.status}).",
            )
        if not short.output_path.is_file() or short.output_path.stat().st_size == 0:
            return ShortUploadResult(
                short.candidate_id, short.output_path, "error",
                error=f"Fichier video introuvable ou vide : {short.output_path}",
            )

        try:
            video_id, url = self._uploader(
                short.output_path,
                metadata.title,
                metadata.description,
                UPLOAD_PRIVACY,
                self.client_secrets_path,
                self.token_path,
                made_for_kids=False,
                expected_channel_id=self.expected_channel_id,
            )
        except Exception as error:
            self._record_error(manifest_path, short.candidate_id, str(error))
            return ShortUploadResult(
                short.candidate_id, short.output_path, "error",
                title=metadata.title, error=str(error),
            )
        if not isinstance(video_id, str) or not video_id:
            error = "YouTube n'a pas confirme l'upload (aucun identifiant video)."
            self._record_error(manifest_path, short.candidate_id, error)
            return ShortUploadResult(
                short.candidate_id, short.output_path, "error",
                title=metadata.title, error=error,
            )

        try:
            self._record_upload(manifest_path, short, metadata, video_id, url)
        except (OSError, ValueError) as error:
            # Uploaded but not recorded: keep the file so nothing is lost.
            return ShortUploadResult(
                short.candidate_id, short.output_path, "uploaded",
                video_id=video_id, url=url, title=metadata.title,
                error=f"Upload confirme mais manifest non mis a jour : {error}",
            )
        deleted = self._delete_local(short.output_path) if self.delete_after_upload else False
        return ShortUploadResult(
            short.candidate_id,
            short.output_path,
            "uploaded",
            video_id=video_id,
            url=url,
            title=metadata.title,
            local_file_deleted=deleted,
        )

    # ------------------------------------------------------------------
    # Manifest helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_manifest(path: Path) -> dict[str, Any]:
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Unable to read VOD manifest: {error}") from error
        if not isinstance(manifest, dict):
            raise ValueError("VOD manifest has an invalid format.")
        return manifest

    def _record_upload(
        self,
        manifest_path: Path,
        short: VODShortResult,
        metadata: ShortMetadata,
        video_id: str,
        url: str,
    ) -> None:
        manifest = self._load_manifest(manifest_path)
        uploads = manifest.get("youtube_uploads")
        if not isinstance(uploads, dict):
            uploads = {}
        uploads[short.candidate_id] = {
            "video_id": video_id,
            "url": url,
            "privacy": UPLOAD_PRIVACY,
            "title": metadata.title,
            "description": metadata.description,
            "file": short.output_path.name,
            "start": short.start,
            "end": short.end,
            "gemini_score": short.gemini_score,
            "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        manifest["youtube_uploads"] = uploads
        errors = manifest.get("youtube_upload_errors")
        if isinstance(errors, dict):
            errors.pop(short.candidate_id, None)
            if not errors:
                manifest.pop("youtube_upload_errors", None)
        self._write_manifest(manifest_path, manifest)

    def _record_error(self, manifest_path: Path, candidate_id: str, error: str) -> None:
        try:
            manifest = self._load_manifest(manifest_path)
            errors = manifest.get("youtube_upload_errors")
            if not isinstance(errors, dict):
                errors = {}
            errors[candidate_id] = error
            manifest["youtube_upload_errors"] = errors
            self._write_manifest(manifest_path, manifest)
        except (OSError, ValueError):
            pass  # Keep the original upload error visible to the caller.

    @staticmethod
    def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f"{path.name}.tmp")
        temporary_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(path)

    @staticmethod
    def _delete_local(path: Path) -> bool:
        if path.suffix.lower() != ".mp4" or not path.name.endswith("_short.mp4"):
            return False  # Only generated Shorts may be cleaned up.
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        except OSError:
            return False
        return True


def format_short_upload_result(result: ShortUploadResult) -> str:
    if result.status == "uploaded":
        cleanup = "fichier local supprime" if result.local_file_deleted else "fichier local conserve"
        line = f"  [publie prive] {result.candidate_id} -> {result.url} ({cleanup})"
        return f"{line} - {result.error}" if result.error else line
    if result.status == "already_uploaded":
        return f"  [deja publie] {result.candidate_id} -> {result.url}"
    if result.status == "skipped":
        return f"  [non publie] {result.candidate_id} : {result.error}"
    return f"  [echec upload] {result.candidate_id} : {result.error} (fichier local conserve)"
