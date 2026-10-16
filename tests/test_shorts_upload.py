"""Tests for private YouTube publication and post-upload cleanup."""

from pathlib import Path
import json
import tempfile
import unittest

from twitch_auto_clipper.shorts_metadata import ShortMetadata
from datetime import date, datetime, timedelta, timezone

from twitch_auto_clipper.daily_quota import DailyQuota
from twitch_auto_clipper.shorts_upload import VODShortsUploader, format_short_upload_result
from twitch_auto_clipper.vod_shorts import VODShortResult
from twitch_auto_clipper.youtube import YouTubeUploadError

METADATA = ShortMetadata(title="Streamer: “no way”", description="“no way”")


class ShortsUploadTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.source = self.tmp / "vod_1.mp4"
        self.source.write_bytes(b"source")
        self.transcript = self.tmp / "vod_1_transcript.json"
        self.transcript.write_text("[]", encoding="utf-8")
        self.manifest = self.tmp / "vod_1_processing.json"
        self.manifest.write_text(json.dumps({"vod_id": "vod_1"}), encoding="utf-8")
        self.short_path = self.tmp / "vod_1_candidate_1_short.mp4"
        self.short_path.write_bytes(b"short")

    def tearDown(self):
        self._tmp.cleanup()

    def _short(self, status="generated"):
        return VODShortResult(
            vod_id="vod_1", candidate_id="candidate_1", source_path=self.source,
            output_path=self.short_path, start=15.0, end=35.0, clip_budget=2,
            gemini_score=88.0, gemini_justification="why", status=status,
        )

    def _manifest(self):
        return json.loads(self.manifest.read_text(encoding="utf-8"))

    def _assert_protected_files_kept(self):
        self.assertTrue(self.source.is_file())
        self.assertTrue(self.transcript.is_file())
        self.assertTrue(self.manifest.is_file())

    def test_confirmed_upload_is_private_recorded_and_deletes_local_short(self):
        calls = []

        def uploader(path, title, description, privacy, secrets, token, **kwargs):
            calls.append((path, title, privacy, kwargs))
            return "yt123", "https://www.youtube.com/watch?v=yt123"

        result = VODShortsUploader(self.tmp, uploader=uploader).upload("vod_1", self._short(), METADATA)

        self.assertEqual(result.status, "uploaded")
        self.assertTrue(result.local_file_deleted)
        self.assertFalse(self.short_path.exists())
        self.assertEqual(calls[0][2], "private")
        self.assertFalse(calls[0][3]["made_for_kids"])
        self.assertFalse(calls[0][3]["allow_browser"])  # unattended upload never waits for a sign-in
        record = self._manifest()["youtube_uploads"]["candidate_1"]
        self.assertEqual(record["video_id"], "yt123")
        self.assertEqual(record["privacy"], "private")
        self.assertEqual(record["title"], METADATA.title)
        self._assert_protected_files_kept()

    def test_visibility_is_private_unless_configured(self):
        calls = []

        def uploader(path, title, description, privacy, *args, **kwargs):
            calls.append(privacy)
            return "yt1", "https://youtu.be/yt1"

        VODShortsUploader(self.tmp, uploader=uploader, privacy="public").upload("vod_1", self._short(), METADATA)
        self.assertEqual(calls, ["public"])
        self.assertEqual(self._manifest()["youtube_uploads"]["candidate_1"]["privacy"], "public")
        with self.assertRaises(ValueError):
            VODShortsUploader(self.tmp, privacy="everyone")

    def test_failed_upload_keeps_local_short(self):
        def uploader(*args, **kwargs):
            raise YouTubeUploadError("quota exceeded")

        result = VODShortsUploader(self.tmp, uploader=uploader).upload("vod_1", self._short(), METADATA)

        self.assertEqual(result.status, "error")
        self.assertTrue(self.short_path.is_file())
        self.assertNotIn("youtube_uploads", self._manifest())
        self.assertIn("quota", self._manifest()["youtube_upload_errors"]["candidate_1"])
        self._assert_protected_files_kept()

    def test_unexpected_exception_keeps_local_short(self):
        def uploader(*args, **kwargs):
            raise ConnectionResetError("network dropped")

        result = VODShortsUploader(self.tmp, uploader=uploader).upload("vod_1", self._short(), METADATA)

        self.assertEqual(result.status, "error")
        self.assertTrue(self.short_path.is_file())

    def test_interruption_propagates_and_keeps_local_short(self):
        def uploader(*args, **kwargs):
            raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            VODShortsUploader(self.tmp, uploader=uploader).upload("vod_1", self._short(), METADATA)
        self.assertTrue(self.short_path.is_file())
        self.assertNotIn("youtube_uploads", self._manifest())

    def test_unconfirmed_upload_without_video_id_keeps_local_short(self):
        result = VODShortsUploader(self.tmp, uploader=lambda *a, **k: ("", "")).upload(
            "vod_1", self._short(), METADATA
        )
        self.assertEqual(result.status, "error")
        self.assertTrue(self.short_path.is_file())

    def test_already_uploaded_short_is_not_uploaded_twice(self):
        self.manifest.write_text(json.dumps({"youtube_uploads": {
            "candidate_1": {"video_id": "old", "url": "https://youtu.be/old"}
        }}), encoding="utf-8")
        calls = []
        result = VODShortsUploader(self.tmp, uploader=lambda *a, **k: calls.append(a)).upload(
            "vod_1", self._short(), METADATA
        )
        self.assertEqual(result.status, "already_uploaded")
        self.assertEqual(result.video_id, "old")
        self.assertEqual(calls, [])

    def test_errored_short_is_skipped(self):
        calls = []
        result = VODShortsUploader(self.tmp, uploader=lambda *a, **k: calls.append(a)).upload(
            "vod_1", self._short(status="error"), METADATA
        )
        self.assertEqual(result.status, "skipped")
        self.assertEqual(calls, [])

    def test_cleanup_never_deletes_non_short_files(self):
        self.assertFalse(VODShortsUploader._delete_local(self.source))
        self.assertFalse(VODShortsUploader._delete_local(self.transcript))
        self._assert_protected_files_kept()

    def test_daily_quota_defers_without_calling_youtube(self):
        calls = []
        uploader = VODShortsUploader(self.tmp, uploader=lambda *a, **k: calls.append(a), daily_upload_limit=1)
        uploader.quota.record_use()

        result = uploader.upload("vod_1", self._short(), METADATA)

        self.assertEqual(result.status, "deferred")
        self.assertEqual(calls, [])
        self.assertTrue(self.short_path.is_file())
        self.assertIn("en attente", format_short_upload_result(result))

    def test_format_mentions_kept_file_on_failure(self):
        result = VODShortsUploader(
            self.tmp, uploader=lambda *a, **k: (_ for _ in ()).throw(YouTubeUploadError("x"))
        ).upload("vod_1", self._short(), METADATA)
        self.assertIn("fichier local conserve", format_short_upload_result(result))


class PublishNextTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.uploaded = []

    def tearDown(self):
        self._tmp.cleanup()

    def _vod(self, vod_id, scores, status="completed", budget=2):
        generated, metadata = {}, {}
        for index, score in enumerate(scores):
            key = f"{index}.0-{index + 5}.0"
            (self.tmp / f"{vod_id}_{key}_short.mp4").write_bytes(b"short")
            generated[key] = {"candidate_id": f"candidate_{index + 1}", "file": f"{vod_id}_{key}_short.mp4",
                              "start": float(index), "end": index + 5.0, "gemini_score": score,
                              "profanity_filtered": True}
            metadata[key] = {"title": f"{vod_id} {score}", "description": "d"}
        (self.tmp / f"{vod_id}_processing.json").write_text(json.dumps({
            "vod_id": vod_id, "clip_budget": budget, "automation_status": status,
            "generated_shorts": generated, "shorts_metadata": metadata,
        }), encoding="utf-8")

    def _upload(self, path, title, *args, **kwargs):
        self.uploaded.append(title)
        return f"yt{len(self.uploaded)}", "https://youtu.be/x"

    def test_best_score_of_all_completed_vods_goes_first(self):
        self._vod("early", [60, 70])
        self._vod("late", [95])
        self._vod("running", [99], status="partial")  # still being processed
        uploader = VODShortsUploader(self.tmp, uploader=self._upload)
        while uploader.publish_next():
            pass
        self.assertEqual(self.uploaded, ["late 95", "early 70", "early 60"])

    def test_shorts_rendered_without_the_profanity_filter_are_never_published(self):
        self._vod("old", [99])
        manifest = self.tmp / "old_processing.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        for record in data["generated_shorts"].values():
            record.pop("profanity_filtered")
        manifest.write_text(json.dumps(data), encoding="utf-8")
        self._vod("new", [50])
        uploader = VODShortsUploader(self.tmp, uploader=self._upload)
        while uploader.publish_next():
            pass
        self.assertEqual(self.uploaded, ["new 50"])

    def test_a_failed_short_goes_after_the_others(self):
        self._vod("v", [90, 50])
        fail = [True]

        def flaky(path, title, *args, **kwargs):
            if fail.pop() if fail else False:
                raise RuntimeError("network")
            return self._upload(path, title)

        uploader = VODShortsUploader(self.tmp, uploader=flaky)
        self.assertEqual(uploader.publish_next()[1].status, "error")
        uploader.publish_next()
        self.assertEqual(self.uploaded, ["v 50"])  # the failed one waits behind
        uploader.publish_next()
        self.assertEqual(self.uploaded, ["v 50", "v 90"])

    def _clocked(self, now, limit=20, rolls=lambda: 0.0, top=()):
        return VODShortsUploader(
            self.tmp, uploader=self._upload, daily_upload_limit=limit,
            clock=lambda: now[0], random_source=rolls, top_streamers=frozenset(top),
        )

    def test_uploads_start_as_soon_as_youtube_allows_them(self):
        self._vod("v", [90, 80])
        batch = datetime(2026, 10, 15, 17, 0, tzinfo=timezone.utc)
        (self.tmp / "youtube_uploads.json").write_text(json.dumps({  # 10 uploads yesterday at 17:00
            "uses": [(batch + timedelta(minutes=i)).isoformat() for i in range(10)], "retry_after": None,
        }), encoding="utf-8")
        now = [batch + timedelta(hours=23, minutes=59)]
        uploader = self._clocked(now, limit=10)
        self.assertIsNone(uploader.publish_next())  # still 10 uploads in the last 24 hours
        now[0] = batch + timedelta(hours=24)
        self.assertIsNotNone(uploader.publish_next())  # the first one is 24 hours old
        self.assertEqual(self.uploaded, ["v 90"])

    def test_the_hour_spreads_the_day_quota_at_random_moments(self):
        import random

        self._vod("v", list(range(50, 75)))  # 25 ready Shorts, 20 allowed
        now = [datetime(2026, 10, 16, 7, 0, tzinfo=timezone.utc)]
        uploader = self._clocked(now, rolls=random.Random(4).random)
        moments = []
        while now[0] < datetime(2026, 10, 16, 8, 0, tzinfo=timezone.utc):
            if uploader.publish_next():
                moments.append(now[0])
            now[0] += timedelta(seconds=60)
        self.assertEqual(len(moments), 20)
        self.assertGreater(moments[-1] - moments[0], timedelta(minutes=30))  # not all at once
        self.assertLess(moments[-1], datetime(2026, 10, 16, 8, 0, tzinfo=timezone.utc))
        self.assertEqual(self.uploaded[0], "v 74")  # best first

    def test_a_refusal_keeps_every_short_for_the_next_day(self):
        self._vod("v", [90, 80, 70])
        now = [datetime(2026, 10, 16, 7, 0, tzinfo=timezone.utc)]
        uploader = self._clocked(now, limit=10)
        uploader._uploader = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('<HttpError 403 "reason": "uploadLimitExceeded">'))
        vod_id, result = uploader.publish_next()
        self.assertEqual(result.status, "deferred")
        self.assertIn("uploadLimitExceeded", result.error)
        self.assertEqual(len(list(self.tmp.glob("v_*_short.mp4"))), 3)  # nothing was published: nothing deleted
        self.assertIsNone(uploader.publish_next())  # paused after the refusal
        uploader._uploader = self._upload
        now[0] += timedelta(hours=1)
        self.assertIsNotNone(uploader.publish_next())  # tried again an hour later
        self.assertEqual(self.uploaded, ["v 90"])

    def _age(self, vod_id, moment):
        import os

        for short in self.tmp.glob(f"{vod_id}_*_short.mp4"):
            os.utime(short, (moment.timestamp(), moment.timestamp()))

    def test_the_reserve_keeps_only_the_best_shorts_for_two_weeks_at_most(self):
        from twitch_auto_clipper.shorts_upload import RESERVE_SIZE

        self._vod("old", [95])
        self._age("old", datetime(2026, 10, 3, tzinfo=timezone.utc))  # 13 days old, among the best
        self._vod("stale", [98])
        self._age("stale", datetime(2026, 10, 1, 11, 0, tzinfo=timezone.utc))  # 15 days old: deleted
        self._vod("new", list(range(1, RESERVE_SIZE + 5)))
        now = [datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)]
        uploader = self._clocked(now, limit=10, rolls=lambda: 1.0)  # no upload due
        self.assertIsNone(uploader.publish_next())
        kept = sorted(self.tmp.glob("*_short.mp4"))
        self.assertEqual(len(kept), RESERVE_SIZE)
        self.assertTrue(any(p.name.startswith("old_") for p in kept))
        self.assertFalse(any(p.name.startswith("stale_") for p in kept))
        self.assertFalse(any(p.name.startswith("new_0.0-") for p in kept))  # the worst score went
        self._vod("better", [99])  # a better newcomer pushes the worst kept one out
        uploader.publish_next()
        self.assertEqual(len(list(self.tmp.glob("*_short.mp4"))), RESERVE_SIZE)
        self.assertTrue(any(p.name.startswith("better_") for p in self.tmp.glob("*_short.mp4")))

    def test_a_short_with_muted_swear_words_must_be_clearly_better(self):
        self._vod("clean", [80])
        self._vod("swears", [85, 95])
        manifest = self.tmp / "swears_processing.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        for record in data["generated_shorts"].values():
            record["muted"] = True
        manifest.write_text(json.dumps(data), encoding="utf-8")
        uploader = VODShortsUploader(self.tmp, uploader=self._upload)
        while uploader.publish_next():
            pass
        self.assertEqual(self.uploaded, ["swears 95", "clean 80", "swears 85"])  # 95-10 > 80 > 85-10

    def test_favored_streamers_get_a_score_bonus(self):
        self._vod("listed", [70])
        self._vod("favored", [60])
        self._vod("plain", [74])
        for vod_id, login in (("listed", "xqc"), ("favored", "emiru"), ("plain", "small")):
            manifest = self.tmp / f"{vod_id}_processing.json"
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data.update(broadcaster_login=login, peak_viewers=20000)
            manifest.write_text(json.dumps(data), encoding="utf-8")
        uploader = VODShortsUploader(
            self.tmp, uploader=self._upload,
            top_streamers=frozenset({"xqc", "emiru", "other_top"}), favored_streamers=frozenset({"Emiru"}),
        )
        while uploader.publish_next():
            pass
        self.assertEqual(self.uploaded, ["favored 60", "listed 70", "plain 74"])  # 60 + 15 > 70

    def test_a_standout_top_streamer_goes_first_then_the_list_then_the_others(self):
        self._vod("other", [99], budget=5)
        self._vod("listed", [60], budget=20)
        self._vod("star", [40, 30], budget=20)
        for vod_id, login, peak in (("other", "small", 5000), ("listed", "xqc", 30000), ("star", "kaicenat", 90000)):
            manifest = self.tmp / f"{vod_id}_processing.json"
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data.update(broadcaster_login=login, peak_viewers=peak)
            manifest.write_text(json.dumps(data), encoding="utf-8")
        uploader = VODShortsUploader(self.tmp, uploader=self._upload, top_streamers=frozenset({"KaiCenat", "xqc"}))
        while uploader.publish_next():
            pass
        self.assertEqual(self.uploaded, ["star 40", "star 30", "listed 60", "other 99"])

        self.uploaded.clear()
        self._vod("star", [40], budget=20)  # 40000 peak: no longer twice xqc's
        data = json.loads((self.tmp / "star_processing.json").read_text(encoding="utf-8"))
        data.update(broadcaster_login="kaicenat", peak_viewers=40000)
        (self.tmp / "star_processing.json").write_text(json.dumps(data), encoding="utf-8")
        self._vod("listed", [60], budget=20)
        data = json.loads((self.tmp / "listed_processing.json").read_text(encoding="utf-8"))
        data.update(broadcaster_login="xqc", peak_viewers=30000)
        (self.tmp / "listed_processing.json").write_text(json.dumps(data), encoding="utf-8")
        while uploader.publish_next():
            pass
        self.assertEqual(self.uploaded, ["listed 60", "star 40"])  # best score of the list


class RollingQuotaTests(unittest.TestCase):
    def test_uses_count_over_a_rolling_24_hours_and_survive_a_restart(self):
        from twitch_auto_clipper.daily_quota import RollingQuota

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "uploads.json"
            now = [datetime(2026, 10, 15, 17, 0, tzinfo=timezone.utc)]
            quota = RollingQuota(path, limit=2, clock=lambda: now[0])
            quota.record_use()
            now[0] += timedelta(hours=10)
            quota.record_use()
            self.assertFalse(RollingQuota(path, 2, clock=lambda: now[0]).available())
            self.assertEqual(quota.next_reset(), datetime(2026, 10, 16, 17, 0, tzinfo=timezone.utc))
            now[0] = datetime(2026, 10, 16, 17, 0, tzinfo=timezone.utc)
            self.assertEqual(quota.remaining(), 1)  # the first use left the window
            quota.mark_exhausted()  # YouTube refused anyway
            self.assertEqual(quota.remaining(), 0)
            now[0] += timedelta(hours=1)
            self.assertEqual(quota.remaining(), 1)


class DailyQuotaTests(unittest.TestCase):
    def test_quota_day_follows_midnight_pacific_time_and_is_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            now = [datetime(2026, 10, 16, 6, 59, tzinfo=timezone.utc)]  # 23:59 PDT
            path = Path(directory) / "quota.json"
            quota = DailyQuota(path, daily_limit=2, clock=lambda: now[0])
            quota.record_use()
            quota.record_use()
            self.assertFalse(DailyQuota(path, 2, clock=lambda: now[0]).available())  # survives a restart
            self.assertEqual(quota.next_reset(), datetime(2026, 10, 16, 7, 0, tzinfo=timezone.utc))
            now[0] = datetime(2026, 10, 16, 7, 0, tzinfo=timezone.utc)
            self.assertTrue(quota.available())  # new YouTube quota day
            quota.mark_exhausted()
            self.assertFalse(quota.available())
            self.assertEqual(quota.next_reset(), datetime(2026, 10, 17, 7, 0, tzinfo=timezone.utc))

    def test_winter_reset_is_one_hour_later_in_utc(self):
        from twitch_auto_clipper.daily_quota import _pacific_midnight

        self.assertEqual(_pacific_midnight(date(2026, 10, 31)), datetime(2026, 10, 31, 7, tzinfo=timezone.utc))
        self.assertEqual(_pacific_midnight(date(2026, 11, 1)), datetime(2026, 11, 1, 7, tzinfo=timezone.utc))
        self.assertEqual(_pacific_midnight(date(2026, 11, 2)), datetime(2026, 11, 2, 8, tzinfo=timezone.utc))
        self.assertEqual(_pacific_midnight(date(2027, 3, 14)), datetime(2027, 3, 14, 8, tzinfo=timezone.utc))
        self.assertEqual(_pacific_midnight(date(2027, 3, 15)), datetime(2027, 3, 15, 7, tzinfo=timezone.utc))

if __name__ == "__main__":
    unittest.main()
