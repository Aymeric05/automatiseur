"""Publish generated Shorts to YouTube and clean up confirmed uploads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import random
from typing import Any, Callable, NamedTuple

from .daily_quota import RollingQuota
from .lessons import record_rejection
from .shorts_metadata import ShortMetadata
from .streamer_lists import add_streamer, load_top_streamers
from .vod_shorts import VODShortResult
from .youtube import fetch_video_statistics, find_uploaded_video, upload_video

UPLOAD_PRIVACY = "private"  # default visibility of automatic uploads
UPLOAD_PRIVACIES = frozenset({"private", "unlisted", "public"})
QUOTA_ERROR_REASONS = ("quotaExceeded", "uploadLimitExceeded", "dailyLimitExceeded")
# The reserve keeps the best Shorts only: the next ones to publish (as many as
# YouTube allows in 24 hours) and backups, ready to go when the computer is
# turned on before new Shorts are rendered. Worse ones are deleted at once.
RESERVE_SIZE = 30
# Only the best of a real choice goes out: below this many ready Shorts, wait for more
# (an unused upload slot is not lost: it stays free until used).
RESERVE_MIN_TO_PUBLISH = 10
MIN_PUBLISHED_SECONDS = 15.0  # shorter, nobody understands the situation
RESERVE_MAX_AGE = timedelta(days=14)  # older Shorts leave the reserve
# A Short with muted swear words must be clearly better to beat a clean one.
PROFANITY_PENALTY = 10
PUBLICATION_HOUR = timedelta(hours=1)
# Gemini compares the reserve's Shorts side by side when it changed, at most this often.
ARBITRATION_INTERVAL = timedelta(hours=3)
STATISTICS_INTERVAL = timedelta(hours=6)  # views of the published Shorts, read 4 times a day
# Views kept at these ages (days), to compare Shorts published on different days.
VIEW_SNAPSHOT_DAYS = (1, 3, 7)
STATISTICS_DAYS = 30  # Shorts followed after their publication
PUBLICATION_MARGIN = timedelta(minutes=5)
# A top streamer "stands out" with at least this many times the peak viewers of the next one.
STANDOUT_FACTOR = 2
FAVORED_SCORE_BONUS = 15  # added to the Gemini score (0-100) of favored streamers' Shorts
# The biggest streamers of the list win at a similar quality: (rank at most, bonus).
RANK_BONUSES = ((5, 10), (15, 5))
# Streamers whose Shorts get more views than the channel's usual win a few points, and those
# below it lose a few (except the listed ones). Shorts views are partly luck: the effect stays
# small and grows with the number of Shorts measured.
AUDIENCE_POINTS_PER_DECADE = 4  # 10 times the channel's usual views (in log scale)
AUDIENCE_PRIOR_SHORTS = 4  # a streamer's average counts for n / (n + 4): 2 Shorts weigh a third
AUDIENCE_MAX_POINTS = 3


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
        streamer_ranks: dict[str, int] | None = None,
        check_seconds: float = 60.0,
        min_reserve: int = RESERVE_MIN_TO_PUBLISH,
        clock: Callable[[], datetime] | None = None,
        random_source: Callable[[], float] = random.random,
        statistics_fetcher: Callable[..., dict[str, dict[str, int]]] | None = None,
        uploaded_finder: Callable[..., tuple[str, str] | None] | None = None,
        retention_fetcher: Callable[[list[str], str], dict[str, dict[str, float]]] | None = None,
        blocked_streamers_path: Path | None = None,
        channel: str = "gaming",
        publishing: bool = True,
        arbiter: Callable[[list[dict[str, Any]]], dict[str, float]] | None = None,
    ) -> None:
        if privacy not in UPLOAD_PRIVACIES:
            raise ValueError(f"privacy must be one of {sorted(UPLOAD_PRIVACIES)}")
        self.output_dir = output_dir
        # YouTube keeps uploads of an API project it has not audited private anyway.
        self.privacy = privacy
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        # The YouTube channel this publisher fills ("gaming" or "irl"): only its Shorts, with
        # its own state files (the gaming channel keeps the original names).
        self.channel = channel
        # False until the channel is authorized: its reserve is kept up to date, nothing is uploaded.
        self.publishing = publishing
        prefix = "" if channel == "gaming" else f"{channel}_"
        # Uploads allowed in any 24 hours (YouTube's limit is a rolling window, per channel).
        # None: no local limit and no spreading (YouTube's refusals are still honoured).
        self.quota = (
            RollingQuota(output_dir / f"{prefix}youtube_uploads.json", daily_upload_limit, clock=self._clock)
            if daily_upload_limit is not None
            else None
        )
        self.schedule_path = output_dir / f"{prefix}publication_hour.json"
        self.top_streamers = frozenset(login.lower() for login in top_streamers)
        self.favored_streamers = frozenset(login.lower() for login in favored_streamers)
        # Position in this channel's top streamers list (1 = first): the higher, the bigger the bonus.
        self.streamer_ranks = {login.lower(): rank for login, rank in (streamer_ranks or {}).items()}
        self.check_seconds = check_seconds  # how often publish_next is called
        self.min_reserve = min_reserve  # with a limit: ready Shorts needed before publishing
        self._random = random_source
        # Every published Short, with its views: what works best is measured, not guessed.
        self.history_path = output_dir / "published_shorts.json"
        self._statistics_fetcher = statistics_fetcher or fetch_video_statistics
        # Finds an upload YouTube received although the app saw it fail (never sent twice).
        self._uploaded_finder = uploaded_finder or find_uploaded_video
        # Share of each Short watched (YouTube Analytics); None: views only.
        self._retention_fetcher = retention_fetcher
        # No Short of these streamers is published; one gets added when YouTube removes,
        # rejects or blocks one of their Shorts (see refresh_statistics).
        self.blocked_streamers_path = blocked_streamers_path
        self._statistics_retry_at: datetime | None = None
        # Comparative scores of the reserve (see _arbitrate); None: per-live Gemini scores only.
        self._arbiter = arbiter
        self.arbitration_path = output_dir / f"{prefix}reserve_ranking.json"
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
        errors = manifest.get("youtube_upload_errors")
        if isinstance(errors, dict) and short.key in errors:
            # Its last upload failed: it may have reached YouTube anyway (a drop before the answer).
            try:
                found = self._uploaded_finder(
                    metadata.title, self.client_secrets_path, self.token_path, self.expected_channel_id
                )
            except Exception:
                found = None  # unknown: the upload below is tried as usual
            if found:
                return self._uploaded(manifest, manifest_path, short, metadata, *found)
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
                category_id="20" if self.channel == "gaming" else "24",  # Gaming, else Entertainment
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
        return self._uploaded(manifest, manifest_path, short, metadata, video_id, url)

    def _uploaded(
        self, manifest: dict[str, Any], manifest_path: Path, short: VODShortResult,
        metadata: ShortMetadata, video_id: str, url: str,
    ) -> ShortUploadResult:
        """Record a Short that is on YouTube, then delete the local copy."""
        self._record_publication(manifest, short, metadata, video_id, url)
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
        key = self._rank_key(ready)
        ready.sort(key=key, reverse=True)
        for position, item in enumerate(ready[RESERVE_SIZE:], start=RESERVE_SIZE + 1):
            # Pushed out of the reserve by better ones: remembered with why, so the selection learns.
            self._reject(item.vod_id, item.login, item.short, item.metadata.title, key(item)[3], key(ready[RESERVE_SIZE - 1])[3],
                         f"{position}e de la reserve, seuls les {RESERVE_SIZE} meilleurs restent")
            self._delete_local(item.short.output_path)
        ready = ready[:RESERVE_SIZE]
        if self._arbitrate(ready):
            ready.sort(key=self._rank_key(ready), reverse=True)
        if not ready or not self.publishing or (
            self.quota is not None
            and (len(ready) < self.min_reserve or not self._upload_due(self._publication_window()))
        ):
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
        score (plus ``FAVORED_SCORE_BONUS`` for ``favored_streamers`` and
        ``RANK_BONUSES`` for the first ones of the list, plus or minus a few
        ``_audience_points``, minus ``PROFANITY_PENALTY`` when swear words were
        muted), then the biggest
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
        compared = self._comparative_scores()
        audience = self._audience_points()
        return lambda item: (
            not item.failed,
            item.login == standout,
            item.login in self.top_streamers,
            compared.get(self._reserve_id(item), item.short.gemini_score or 0)
            + (FAVORED_SCORE_BONUS if item.login in self.favored_streamers else 0)
            - (PROFANITY_PENALTY if item.muted else 0)
            + self._rank_bonus(item.login)
            + audience.get(item.login, 0.0),
            item.short.clip_budget,
        )

    def _reject(
        self, vod_id: str, login: str, short: VODShortResult | dict[str, Any], title: str,
        score: float | None, threshold: float | None, reason: str,
    ) -> None:
        get = short.get if isinstance(short, dict) else (lambda name: getattr(short, name, None))
        record_rejection(self.output_dir, {
            "channel": self.channel, "vod_id": vod_id, "streamer": login, "title": title,
            "gemini_score": get("gemini_score"), "justification": get("gemini_justification"),
            "source": get("source"), "emotion": get("emotion"),
            "seconds": round(float(get("end") or 0) - float(get("start") or 0), 1),
            "score": round(score, 1) if score is not None else None,
            "needed": round(threshold, 1) if threshold is not None else None, "reason": reason,
        }, self._clock)

    def would_enter_reserve(self, moment: dict[str, Any], login: str, vod_id: str, clip_budget: int) -> bool:
        """Whether a moment, once rendered, would rank among this channel's best ``RESERVE_SIZE``.

        One that would be deleted right away is never rendered (and is recorded).
        """
        ready = self._ready_shorts()
        if len(ready) < RESERVE_SIZE:
            return True
        key = self._rank_key(ready)
        ready.sort(key=key, reverse=True)
        candidate = _ReadyShort(
            vod_id=vod_id, login=login.lower(), peak_viewers=0, failed=False, muted=False,
            short=VODShortResult(
                vod_id=vod_id, candidate_id="new", source_path="", output_path=Path(), start=0.0, end=0.0,
                clip_budget=clip_budget, gemini_score=float(moment.get("gemini_score") or 0),
                gemini_justification=None, status="already_exists",
            ),
            metadata=ShortMetadata(title="", description=""),
        )
        if key(candidate) > key(ready[RESERVE_SIZE - 1]):
            return True
        self._reject(vod_id, login, moment, str(moment.get("gemini_title") or ""), key(candidate)[3],
                     key(ready[RESERVE_SIZE - 1])[3], "pas rendu : il n'aurait pas battu le 30e de la reserve")
        return False

    def _rank_bonus(self, login: str) -> int:
        rank = self.streamer_ranks.get(login)
        return next((bonus for last, bonus in RANK_BONUSES if rank is not None and rank <= last), 0)

    def _audience_points(self) -> dict[str, float]:
        """A few points per streamer, from the views of their published Shorts.

        Each Short counts with its most mature views (at 7, 3 or 1 days), in
        log scale; a streamer's average is compared with the channel's, pulled
        towards it when few Shorts are measured (``AUDIENCE_PRIOR_SHORTS``) and
        kept within ``AUDIENCE_MAX_POINTS``. A listed streamer never loses points.
        """
        streamers: dict[str, list[float]] = {}
        everyone: list[float] = []
        for entry in self._load_history()["shorts"]:
            views = next(
                (entry[key] for key in ("views_7d", "views_3d", "views_1d")
                 if isinstance(entry.get(key), (int, float))),
                None,
            )
            if views is None:
                continue  # too recent: its views say nothing yet
            everyone.append(math.log10(views + 1))
            if entry.get("streamer"):
                streamers.setdefault(str(entry["streamer"]).lower(), []).append(everyone[-1])
        if not everyone:
            return {}
        usual = sum(everyone) / len(everyone)
        points = {}
        for login, values in streamers.items():
            shift = (
                AUDIENCE_POINTS_PER_DECADE * (sum(values) / len(values) - usual)
                * len(values) / (len(values) + AUDIENCE_PRIOR_SHORTS)
            )
            if login in self.top_streamers:
                shift = max(shift, 0.0)
            points[login] = max(-AUDIENCE_MAX_POINTS, min(AUDIENCE_MAX_POINTS, shift))
        return points

    @staticmethod
    def _reserve_id(item: _ReadyShort) -> str:
        return f"{item.vod_id}:{item.short.key}"

    def _comparative_scores(self) -> dict[str, float]:
        try:
            scores = json.loads(self.arbitration_path.read_text(encoding="utf-8")).get("scores")
        except (OSError, json.JSONDecodeError, AttributeError):
            return {}
        return scores if isinstance(scores, dict) else {}

    def _arbitrate(self, ready: list[_ReadyShort]) -> bool:
        """Have Gemini compare the reserve's Shorts side by side; True when scores changed.

        Each Short's Gemini score was given within its own live: here the
        reserve is ranked as a whole, at most every ``ARBITRATION_INTERVAL``
        and only when its content changed. A failure keeps the previous scores.
        """
        if self._arbiter is None or len(ready) < 2:
            return False
        now = self._clock()
        try:
            state = json.loads(self.arbitration_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {}
        state = state if isinstance(state, dict) else {}
        ids = sorted(self._reserve_id(item) for item in ready)
        try:
            if now - datetime.fromisoformat(state["at"]) < ARBITRATION_INTERVAL:
                return False
        except (KeyError, TypeError, ValueError):
            pass
        if ids == state.get("ids"):
            return False
        described = []
        for item in ready:
            described.append({
                "id": self._reserve_id(item),
                "streamer": item.login,
                "peak_viewers": item.peak_viewers,
                "title": item.metadata.title,
                "description": item.metadata.description.split("\n\n#")[0][:600],
                "seconds": round(item.short.end - item.short.start),
                "live_score": item.short.gemini_score,
                "why": item.short.gemini_justification,
            })
        try:
            scores = self._arbiter(described)
        except Exception:
            scores = None  # Gemini unavailable: retried at the next interval
        self._write_manifest(self.arbitration_path, {
            "at": now.isoformat(), "ids": ids,
            "scores": scores if scores else state.get("scores", {}),
        })
        return bool(scores)

    def _ready_shorts(self) -> list[_ReadyShort]:
        expired_before = (self._clock() - RESERVE_MAX_AGE).timestamp()
        blocked = load_top_streamers(self.blocked_streamers_path) if self.blocked_streamers_path else frozenset()
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
                if (record.get("channel") or "gaming") != self.channel:
                    continue  # the other channel's publisher takes care of it
                path = self.output_dir / str(record.get("file", ""))
                if not path.name.endswith("_short.mp4") or not path.is_file():
                    continue
                try:
                    too_short = float(record["end"]) - float(record["start"]) < MIN_PUBLISHED_SECONDS
                except (KeyError, TypeError, ValueError):
                    too_short = True
                if (
                    not record.get("profanity_filtered") or too_short or path.stat().st_mtime < expired_before
                    or str(manifest.get("broadcaster_login", "")).lower() in blocked
                ):
                    # Rendered before swear words were muted, too short, too old or of a
                    # blocked streamer: never published.
                    if record.get("profanity_filtered") and not too_short and path.stat().st_mtime < expired_before:
                        self._reject(vod_id, str(manifest.get("broadcaster_login", "")), record, str(meta.get("title", "")),
                                     None, None, "jamais publie en 14 jours")
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
                        candidate_start=record.get("candidate_start"),
                        muted=bool(record.get("muted")),
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

    def refresh_statistics(self) -> str | None:
        """Every few hours, read the views of the Shorts published in the last 30 days.

        A Short that YouTube removed (missing at two readings in a row),
        rejected or blocked puts its streamer on the blocked list.

        The views a Short has at 1, 3 and 7 days are kept (``views_1d``...),
        with its retention when ``retention_fetcher`` is set (``retention_pct``:
        average share watched, ``avg_view_seconds``, ``engaged_views``).

        Returns a summary line when they were read (or why they could not be).
        """
        now = self._clock()
        if self._statistics_retry_at is not None and now < self._statistics_retry_at:
            return None
        history = self._load_history()
        last = history.get("fetched_at")
        try:
            if last and now - datetime.fromisoformat(last) < STATISTICS_INTERVAL:
                return None
        except (TypeError, ValueError):
            pass
        followed = []
        for entry in history["shorts"]:
            if entry.get("channel", "gaming") != self.channel:
                continue  # read by the other channel's publisher, with its own authorization
            try:
                if now - datetime.fromisoformat(entry["uploaded_at"]) < timedelta(days=STATISTICS_DAYS):
                    followed.append(entry)
            except (KeyError, TypeError, ValueError):
                continue
        if not followed:
            return None
        try:
            statistics = self._statistics_fetcher(
                [entry["video_id"] for entry in followed], self.client_secrets_path, self.token_path
            )
        except Exception as error:
            self._statistics_retry_at = now + timedelta(hours=1)
            return f"Statistiques YouTube non lues ({error}) : nouvel essai dans une heure."
        newly_blocked = []
        for entry in followed:
            values = dict(statistics.get(entry["video_id"]) or {})
            problem = values.pop("problem", None)
            if not values and not problem:
                # Missing from YouTube: removed (or deleted in Studio). Confirmed at the next reading.
                problem = "retire de YouTube" if entry.get("missing_since") else None
                entry.setdefault("missing_since", now.isoformat(timespec="seconds"))
            else:
                entry.pop("missing_since", None)
            if problem:
                entry["problem"] = problem
                if self.blocked_streamers_path and entry.get("streamer") and add_streamer(
                    self.blocked_streamers_path, entry["streamer"],
                    f"auto {now:%Y-%m-%d}: Short {entry['video_id']} {problem}",
                ):
                    newly_blocked.append(f"{entry['streamer']} ({problem})")
            entry.update(values)
            age = now - datetime.fromisoformat(entry["uploaded_at"])
            for days in VIEW_SNAPSHOT_DAYS:
                if age >= timedelta(days=days) and "views" in entry:
                    entry.setdefault(f"views_{days}d", entry["views"])
        retention_note = ""
        if self._retention_fetcher is not None:
            first_day = min(datetime.fromisoformat(entry["uploaded_at"]) for entry in followed) - timedelta(days=1)
            try:
                retention = self._retention_fetcher(
                    [entry["video_id"] for entry in followed], first_day.date().isoformat()
                )
                for entry in followed:
                    entry.update(retention.get(entry["video_id"], {}))
                retention_note = f" ; retention lue pour {len(retention)} Shorts"
            except Exception as error:  # not authorized or unavailable: views only
                retention_note = f" ; retention non lue ({error})"
        history["fetched_at"] = now.isoformat()
        self._write_manifest(self.history_path, history)
        total = sum(entry.get("views", 0) for entry in followed)
        best = max(followed, key=lambda entry: entry.get("views", 0))
        return (
            f"Statistiques YouTube : {len(followed)} Shorts sur {STATISTICS_DAYS} jours, {total} vues ; "
            f"meilleur : {best.get('title', best['video_id'])} ({best.get('views', 0)} vues)"
            + retention_note
            + (f" ; liste noire : {', '.join(newly_blocked)}" if newly_blocked else "")
        )

    def _load_history(self) -> dict[str, Any]:
        try:
            history = json.loads(self.history_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            history = None
        if not isinstance(history, dict) or not isinstance(history.get("shorts"), list):
            history = {"fetched_at": None, "shorts": []}
        return history

    def _record_publication(
        self, manifest: dict[str, Any], short: VODShortResult, metadata: ShortMetadata,
        video_id: str, url: str,
    ) -> None:
        """Remember the published Short and what it was made of, to compare views later."""
        history = self._load_history()
        lead_in = short.candidate_start - short.start if short.candidate_start is not None else None
        generated = manifest.get("generated_shorts")
        record = generated.get(short.key) if isinstance(generated, dict) else None
        record = record if isinstance(record, dict) else {}
        streamer = str(manifest.get("broadcaster_login", ""))
        history["shorts"].append({
            "video_id": video_id,
            "channel": self.channel,
            "url": url,
            "title": metadata.title,
            "vod_id": short.vod_id,
            "streamer": streamer,
            "list_rank": self.streamer_ranks.get(streamer.lower()),  # place in the channel's top streamers list
            "peak_viewers": manifest.get("peak_viewers"),
            "gemini_score": short.gemini_score,
            "compared_score": self._comparative_scores().get(f"{short.vod_id}:{short.key}"),
            # Where the moment comes from (transcript, chat or emotion) and how it was made.
            **{key: record.get(key) for key in ("source", "emotion", "hook", "focus_x", "max_seconds", "cold_open")},
            "seconds": round(short.end - short.start, 1),
            "lead_in_seconds": round(lead_in, 1) if lead_in is not None else None,
            "muted": short.muted,
            "uploaded_at": self._clock().isoformat(timespec="seconds"),
        })
        try:
            self._write_manifest(self.history_path, history)
        except OSError:
            pass  # the upload itself is recorded in the VOD manifest

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
