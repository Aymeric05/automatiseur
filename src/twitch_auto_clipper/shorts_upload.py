"""Publish generated Shorts to YouTube and clean up confirmed uploads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import random
from typing import Any, Callable, NamedTuple

from .daily_quota import RollingQuota
from .shorts_metadata import ShortMetadata
from .vod_shorts import VODShortResult
from .youtube import upload_video

UPLOAD_PRIVACY = "private"  # default visibility of automatic uploads
UPLOAD_PRIVACIES = frozenset({"private", "unlisted", "public"})
QUOTA_ERROR_REASONS = ("quotaExceeded", "uploadLimitExceeded", "dailyLimitExceeded")
# The reserve keeps the best Shorts only: the next ones to publish (as many as
# YouTube allows in 24 hours) and backups, ready to go when the computer is
# turned on before new Shorts are rendered. Worse ones are deleted at once.
RESERVE_SIZE = 30
RESERVE_MAX_AGE = timedelta(days=14)  # older Shorts leave the reserve
# A Short with muted swear words must be clearly better to beat a clean one.
PROFANITY_PENALTY = 10
PUBLICATION_HOUR = timedelta(hours=1)
PUBLICATION_MARGIN = timedelta(minutes=5)
# A top streamer "stands out" with at least this many times the peak viewers of the next one.
STANDOUT_FACTOR = 2
FAVORED_SCORE_BONUS = 15  # added to the Gemini score (0-100) of favored streamers' Shorts


@dataclass(frozen=True)
class ShortUploadResult:
    candidate_id: str
    output_path: Path
    status: str  # "uploaded" | "already_uploaded" | "deferred" | "skipped" | "error"
    video_id: str | None = None
    url: str | None = None
    title: str | None = None
    local_file_deleted: bool = False
    error: str | None = None


class _ReadyShort(NamedTuple):
    vod_id: str
    login: str
    peak_viewers: int
    failed: bool  # its last upload failed
    muted: bool  # swear words were muted
    short: VODShortResult
    metadata: ShortMetadata


class VODShortsUploader:
    """Upload each generated Short once, then delete the local copy.

    ``publish_next`` keeps the reserve (the best Shorts of every completed
    VOD) and picks which Short goes next.

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
        daily_upload_limit: int | None = None,
        privacy: str = UPLOAD_PRIVACY,
        top_streamers: frozenset[str] = frozenset(),
        favored_streamers: frozenset[str] = frozenset(),
        check_seconds: float = 60.0,
        clock: Callable[[], datetime] | None = None,
        random_source: Callable[[], float] = random.random,
    ) -> None:
        if privacy not in UPLOAD_PRIVACIES:
            raise ValueError(f"privacy must be one of {sorted(UPLOAD_PRIVACIES)}")
        self.output_dir = output_dir
        # YouTube keeps uploads of an API project it has not audited private anyway.
        self.privacy = privacy
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        # Uploads allowed in any 24 hours (YouTube's limit is a rolling window).
        # None: no local limit and no spreading (YouTube's refusals are still honoured).
        self.quota = (
            RollingQuota(output_dir / "youtube_uploads.json", daily_upload_limit, clock=self._clock)
            if daily_upload_limit is not None
            else None
        )
        self.schedule_path = output_dir / "publication_hour.json"
        self.top_streamers = frozenset(login.lower() for login in top_streamers)
        self.favored_streamers = frozenset(login.lower() for login in favored_streamers)
        self.check_seconds = check_seconds  # how often publish_next is called
        self._random = random_source
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
        if isinstance(uploads, dict) and short.key in uploads:
            previous = uploads[short.key]
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
        if self.quota is not None and not self.quota.available():
            return ShortUploadResult(
                short.candidate_id, short.output_path, "deferred", title=metadata.title,
                error=self._deferred_message(),
            )

        try:
            video_id, url = self._uploader(
                short.output_path,
                metadata.title,
                metadata.description,
                self.privacy,
                self.client_secrets_path,
                self.token_path,
                made_for_kids=False,  # never declared "made for kids": widest audience
                expected_channel_id=self.expected_channel_id,
                allow_browser=False,  # unattended: never wait for a sign-in page
            )
        except Exception as error:
            reason = next((reason for reason in QUOTA_ERROR_REASONS if reason in str(error)), None)
            if reason:
                # Not a failure of this Short: YouTube's limit is reached for now.
                if self.quota is not None:
                    self.quota.mark_exhausted()
                return ShortUploadResult(
                    short.candidate_id, short.output_path, "deferred", title=metadata.title,
                    error=f"YouTube refuse l'upload ({reason}). {self._deferred_message()}",
                )
            self._record_error(manifest_path, short.key, str(error))
            return ShortUploadResult(
                short.candidate_id, short.output_path, "error",
                title=metadata.title, error=str(error),
            )
        if not isinstance(video_id, str) or not video_id:
            error = "YouTube n'a pas confirme l'upload (aucun identifiant video)."
            self._record_error(manifest_path, short.key, error)
            return ShortUploadResult(
                short.candidate_id, short.output_path, "error",
                title=metadata.title, error=error,
            )

        if self.quota is not None:
            self.quota.record_use()
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

    def publish_next(self) -> tuple[str, ShortUploadResult] | None:
        """Keep the reserve, and upload its best Short when an upload is due.

        The reserve is every ready Short of the completed VODs, ranked (see
        ``_rank_key``): only the best ``RESERVE_SIZE`` are kept, and each new
        Short takes its place in the ranking. With a limit, uploads are made as
        soon as YouTube allows them (start-up included), spread over an hour
        (see ``_publication_window``). Returns the VOD id and the upload
        result, or None when no upload was due or no Short is ready.
        """
        ready = self._ready_shorts()
        ready.sort(key=self._rank_key(ready), reverse=True)
        for item in ready[RESERVE_SIZE:]:
            self._delete_local(item.short.output_path)  # pushed out of the reserve by better ones
        if not ready or (self.quota is not None and not self._upload_due(self._publication_window())):
            return None
        best = ready[0]
        return best.vod_id, self.upload(best.vod_id, best.short, best.metadata)

    def _publication_window(self) -> tuple[datetime, datetime] | None:
        """The hour over which the uploads YouTube allows are spread.

        A window opens as soon as an upload is possible (at start-up too, when
        the computer was off or asleep) and lasts one hour; another one opens
        whenever uploads are possible again.
        """
        now = self._clock()
        try:
            state = json.loads(self.schedule_path.read_text(encoding="utf-8"))
            window = datetime.fromisoformat(state["start"]), datetime.fromisoformat(state["end"])
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            window = None
        if window is not None and window[0] <= now < window[1]:
            return window
        if self.quota.remaining() <= 0:
            return None
        window = now, now + PUBLICATION_HOUR
        self._write_manifest(self.schedule_path, {"start": window[0].isoformat(), "end": window[1].isoformat()})
        return window

    def _upload_due(self, window: tuple[datetime, datetime] | None) -> bool:
        """Spread the allowed uploads at random moments of the window."""
        if window is None:
            return False
        remaining = self.quota.remaining()
        now = self._clock()
        if remaining <= 0 or not window[0] <= now < window[1]:
            return False
        # Leave a few minutes at the end so the last uploads still fit in the window.
        checks_left = (window[1] - PUBLICATION_MARGIN - now) / timedelta(seconds=self.check_seconds)
        return self._random() < remaining / max(checks_left, 1.0)

    def _rank_key(self, ready: list[_ReadyShort]) -> Callable[[_ReadyShort], tuple[Any, ...]]:
        """Ranking of the reserve, best first with ``reverse=True``.

        A streamer of ``top_streamers`` who clearly stands out (the only one of
        the list with Shorts ready, or at least ``STANDOUT_FACTOR`` times the
        peak viewers of the next one) goes first, then the other listed
        streamers, then everyone else; within each group, the best Gemini
        score (plus ``FAVORED_SCORE_BONUS`` for ``favored_streamers``, minus
        ``PROFANITY_PENALTY`` when swear words were muted), then the biggest
        clip budget. A Short whose last upload failed goes last, so it never
        blocks the others.
        """
        peaks: dict[str, int] = {}
        for item in ready:
            if item.login in self.top_streamers:
                peaks[item.login] = max(peaks.get(item.login, 0), item.peak_viewers)
        ranked = sorted(peaks.items(), key=lambda entry: entry[1], reverse=True)
        standout = (
            ranked[0][0]
            if ranked and (len(ranked) == 1 or ranked[0][1] >= STANDOUT_FACTOR * ranked[1][1])
            else None
        )
        return lambda item: (
            not item.failed,
            item.login == standout,
            item.login in self.top_streamers,
            (item.short.gemini_score or 0)
            + (FAVORED_SCORE_BONUS if item.login in self.favored_streamers else 0)
            - (PROFANITY_PENALTY if item.muted else 0),
            item.short.clip_budget,
        )

    def _ready_shorts(self) -> list[_ReadyShort]:
        expired_before = (self._clock() - RESERVE_MAX_AGE).timestamp()
        ready = []
        for manifest_path in self.output_dir.glob("*_processing.json"):
            try:
                manifest = self._load_manifest(manifest_path)
            except ValueError:
                continue
            if manifest.get("automation_status") != "completed":
                continue  # the worker may still be writing this VOD's files
            vod_id = str(manifest.get("vod_id") or manifest_path.name.removesuffix("_processing.json"))
            uploads, errors, metadata, generated = (
                value if isinstance(value, dict) else {}
                for value in (
                    manifest.get("youtube_uploads"),
                    manifest.get("youtube_upload_errors"),
                    manifest.get("shorts_metadata"),
                    manifest.get("generated_shorts"),
                )
            )
            for key, record in generated.items():
                meta = metadata.get(key)
                if key in uploads or not isinstance(record, dict) or not isinstance(meta, dict):
                    continue
                path = self.output_dir / str(record.get("file", ""))
                if not path.name.endswith("_short.mp4") or not path.is_file():
                    continue
                if not record.get("profanity_filtered") or path.stat().st_mtime < expired_before:
                    # Rendered before swear words were muted, or too old: never published.
                    self._delete_local(path)
                    continue
                try:
                    short = VODShortResult(
                        vod_id=vod_id,
                        candidate_id=str(record.get("candidate_id", key)),
                        source_path="",
                        output_path=path,
                        start=float(record.get("start", 0)),
                        end=float(record.get("end", 0)),
                        clip_budget=int(manifest.get("clip_budget") or 0),
                        gemini_score=float(record.get("gemini_score") or 0),
                        gemini_justification=record.get("gemini_justification"),
                        status="already_exists",
                        clip_id=key,
                    )
                    peak_viewers = int(manifest.get("peak_viewers") or 0)
                except (TypeError, ValueError):
                    continue
                ready.append(_ReadyShort(
                    vod_id=vod_id,
                    login=str(manifest.get("broadcaster_login", "")).lower(),
                    peak_viewers=peak_viewers,
                    failed=key in errors,
                    muted=bool(record.get("muted")),
                    short=short,
                    metadata=ShortMetadata(
                        title=str(meta.get("title", "")), description=str(meta.get("description", "")),
                    ),
                ))
        return ready

    def _deferred_message(self) -> str:
        if self.quota is None:
            return "Nouvel essai au prochain passage."
        retry = self.quota.next_reset()
        return (
            f"Limite YouTube atteinte (au plus {self.quota.limit} envois sur 24 h) : "
            f"nouvel essai apres {retry:%Y-%m-%d %H:%M} UTC."
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
        uploads[short.key] = {
            "candidate_id": short.candidate_id,
            "video_id": video_id,
            "url": url,
            "privacy": self.privacy,
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
            errors.pop(short.key, None)
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
        line = f"  [publie] {result.candidate_id} -> {result.url} ({cleanup})"
        return f"{line} - {result.error}" if result.error else line
    if result.status == "already_uploaded":
        return f"  [deja publie] {result.candidate_id} -> {result.url}"
    if result.status == "skipped":
        return f"  [non publie] {result.candidate_id} : {result.error}"
    if result.status == "deferred":
        return f"  [en attente] {result.candidate_id} : {result.error} (fichier local conserve)"
    return f"  [echec upload] {result.candidate_id} : {result.error} (fichier local conserve)"
