"""Publish generated Shorts to YouTube and clean up confirmed uploads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import random
import time
from typing import Any, Callable, NamedTuple

from .daily_quota import DailyQuota
from .shorts_metadata import ShortMetadata
from .vod_shorts import VODShortResult
from .youtube import upload_video

UPLOAD_PRIVACY = "private"  # default visibility of automatic uploads
UPLOAD_PRIVACIES = frozenset({"private", "unlisted", "public"})
QUOTA_ERROR_REASONS = ("quotaExceeded", "uploadLimitExceeded", "dailyLimitExceeded")
# An unpublished Short older than this is deleted instead of published: newer
# moments are preferred, and unpublished Shorts do not fill the disk.
READY_MAX_AGE = timedelta(hours=48)
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
    short: VODShortResult
    metadata: ShortMetadata


class VODShortsUploader:
    """Upload each generated Short once, then delete the local copy.

    ``publish_next`` picks which Short goes next, among every completed VOD.

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
        # None: no local limit and no publication hour (YouTube's refusals are still honoured).
        self.quota = (
            DailyQuota(output_dir / "youtube_quota.json", daily_upload_limit, clock=self._clock)
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
            if any(reason in str(error) for reason in QUOTA_ERROR_REASONS):
                # Not a failure of this Short: YouTube's daily quota is used up.
                if self.quota is not None:
                    self.quota.mark_exhausted()
                return ShortUploadResult(
                    short.candidate_id, short.output_path, "deferred", title=metadata.title,
                    error=f"YouTube refuse l'upload (quota atteint). {self._deferred_message()}",
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
        """Upload the best Short waiting for publication, when an upload is due.

        Completed VODs leave their Shorts on disk. With a daily limit, the day's
        uploads happen during one publication hour (see ``_publication_hour``),
        each at a random moment of it. Each upload takes the best ready Short
        (see ``_best``). Returns the VOD id and the upload result, or None when
        no upload was due or no Short is ready.
        """
        hour = None
        if self.quota is not None:
            hour = self._publication_hour()
            if not self._upload_due(hour):
                return None
        ready = self._ready_shorts()
        if not ready:
            return None
        best = self._best(ready)
        result = self.upload(best.vod_id, best.short, best.metadata)
        if hour is not None and self.quota.remaining() == 0:
            # The day's publications are over: no Short that was waiting is kept,
            # and the worker then deletes every file of these VODs.
            for item in ready:
                if item is not best:
                    self._delete_local(item.short.output_path)
        return best.vod_id, result

    def _publication_hour(self) -> tuple[datetime, datetime] | None:
        """This quota day's publication hour, or None while it is still to come.

        It is the last hour before the quota reset, so the best Shorts of the
        whole day compete. When the previous day's hour was missed (computer
        off), the hour starts at the next start-up instead; nothing is shifted
        since Shorts stay ready for 48 hours and both days compete.
        """
        now = self._clock()
        reset = self.quota.next_reset()
        day_start = reset - timedelta(days=1)
        today, yesterday = day_start.date().isoformat(), (day_start - timedelta(days=1)).date().isoformat()
        try:
            state = json.loads(self.schedule_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = None
        if not isinstance(state, dict):
            # First run: behave as if yesterday's hour had happened.
            state = {"day": yesterday}
            self._write_manifest(self.schedule_path, state)
        if state.get("day") == today:
            try:
                return datetime.fromisoformat(state["start"]), datetime.fromisoformat(state["end"])
            except (KeyError, TypeError, ValueError):
                return None
        last_hour_start = reset - PUBLICATION_HOUR
        if now >= last_hour_start:
            start, end = last_hour_start, reset
        elif str(state.get("day")) < yesterday:  # yesterday's hour was missed
            start, end = now, min(now + PUBLICATION_HOUR, reset)
        else:
            return None
        self._write_manifest(self.schedule_path, {"day": today, "start": start.isoformat(), "end": end.isoformat()})
        return start, end

    def _upload_due(self, hour: tuple[datetime, datetime] | None) -> bool:
        """Spread the day's uploads at random moments of the publication hour."""
        remaining = self.quota.remaining()
        now = self._clock()
        if hour is None or remaining <= 0 or not hour[0] <= now < hour[1]:
            return False
        # Leave a few minutes at the end so the last uploads still fit in the hour.
        checks_left = (hour[1] - PUBLICATION_MARGIN - now) / timedelta(seconds=self.check_seconds)
        return self._random() < remaining / max(checks_left, 1.0)

    def _best(self, ready: list[_ReadyShort]) -> _ReadyShort:
        """The Short to publish next.

        A streamer of ``top_streamers`` who clearly stands out (the only one of
        the list with Shorts ready, or at least ``STANDOUT_FACTOR`` times the
        peak viewers of the next one) goes first, then the other listed
        streamers, then everyone else; within each group, the best Gemini
        score (plus ``FAVORED_SCORE_BONUS`` for ``favored_streamers``), then the
        biggest clip budget. A Short whose last upload failed
        goes last, so it never blocks the others.
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
        return max(ready, key=lambda item: (
            not item.failed,
            item.login == standout,
            item.login in self.top_streamers,
            (item.short.gemini_score or 0)
            + (FAVORED_SCORE_BONUS if item.login in self.favored_streamers else 0),
            item.short.clip_budget,
        ))

    def _ready_shorts(self) -> list[_ReadyShort]:
        expired_before = time.time() - READY_MAX_AGE.total_seconds()
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
                if path.stat().st_mtime < expired_before:
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
                    short=short,
                    metadata=ShortMetadata(
                        title=str(meta.get("title", "")), description=str(meta.get("description", "")),
                    ),
                ))
        return ready

    def _deferred_message(self) -> str:
        if self.quota is None:
            return "Nouvel essai au prochain passage."
        reset = self.quota.next_reset()
        return (
            f"Quota YouTube du jour atteint ({self.quota.daily_limit} uploads) : "
            f"reprise apres {reset:%Y-%m-%d %H:%M} UTC."
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
