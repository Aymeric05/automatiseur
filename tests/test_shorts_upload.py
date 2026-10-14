"""Tests for private YouTube publication and post-upload cleanup."""

from pathlib import Path
import json
import tempfile
import unittest

from twitch_auto_clipper.shorts_metadata import ShortMetadata
from datetime import datetime, timedelta, timezone

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
                              "start": float(index), "end": index + 5.0, "gemini_score": score}
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

    def test_old_unpublished_shorts_are_dropped(self):
        import os
        import time

        self._vod("old", [99])
        self._vod("new", [50])
        old_file = next(self.tmp.glob("old_*_short.mp4"))
        two_days_ago = time.time() - 49 * 3600
        os.utime(old_file, (two_days_ago, two_days_ago))
        VODShortsUploader(self.tmp, uploader=self._upload).publish_next()
        self.assertEqual(self.uploaded, ["new 50"])
        self.assertFalse(old_file.exists())

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

    def test_uploads_wait_for_the_last_hour_before_the_reset(self):
        self._vod("v", [90, 80])
        now = [datetime(2026, 10, 14, 6, 59, tzinfo=timezone.utc)]  # reset at 08:00 UTC
        uploader = self._clocked(now)
        self.assertIsNone(uploader.publish_next())
        now[0] = datetime(2026, 10, 14, 7, 0, tzinfo=timezone.utc)
        self.assertIsNotNone(uploader.publish_next())
        self.assertEqual(self.uploaded, ["v 90"])

    def test_the_hour_spreads_the_day_quota_at_random_moments(self):
        import random

        self._vod("v", list(range(50, 75)))  # 25 ready Shorts, 20 allowed
        now = [datetime(2026, 10, 14, 7, 0, tzinfo=timezone.utc)]
        uploader = self._clocked(now, rolls=random.Random(4).random)
        moments = []
        while now[0] < datetime(2026, 10, 14, 8, 0, tzinfo=timezone.utc):
            if uploader.publish_next():
                moments.append(now[0])
            now[0] += timedelta(seconds=60)
        self.assertEqual(len(moments), 20)
        self.assertGreater(moments[-1] - moments[0], timedelta(minutes=30))  # not all at once
        self.assertLess(moments[-1], datetime(2026, 10, 14, 8, 0, tzinfo=timezone.utc))
        self.assertEqual(self.uploaded[0], "v 74")  # best first

    def _age(self, vod_id, moment):
        import os

        for short in self.tmp.glob(f"{vod_id}_*_short.mp4"):
            os.utime(short, (moment.timestamp(), moment.timestamp()))

    def test_a_missed_hour_moves_to_the_next_start_up_and_the_losers_go(self):
        self._vod("v", [90, 80, 70])
        self._age("v", datetime(2026, 10, 16, 8, 0, tzinfo=timezone.utc))
        now = [datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)]
        uploader = self._clocked(now, limit=1)
        self.assertIsNone(uploader.publish_next())  # first run: waits for tonight's last hour
        now[0] = datetime(2026, 10, 16, 9, 0, tzinfo=timezone.utc)  # computer off during it
        self.assertIsNotNone(uploader.publish_next())  # catch-up at start-up
        self.assertEqual(list(self.tmp.glob("v_*_short.mp4")), [])  # day's quota used: losers deleted
        self._vod("w", [60])
        self._age("w", datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc))
        now[0] = datetime(2026, 10, 17, 7, 30, tzinfo=timezone.utc)
        self.assertIsNone(uploader.publish_next())  # this quota day already had its hour
        now[0] = datetime(2026, 10, 18, 7, 30, tzinfo=timezone.utc)
        self.assertIsNotNone(uploader.publish_next())  # back to the normal hour
        self.assertEqual(self.uploaded, ["v 90", "w 60"])

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


class DailyQuotaTests(unittest.TestCase):
    def test_quota_day_starts_at_08_utc_and_is_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            now = [datetime(2026, 10, 12, 7, 59, tzinfo=timezone.utc)]
            path = Path(directory) / "quota.json"
            quota = DailyQuota(path, daily_limit=2, clock=lambda: now[0])
            quota.record_use()
            quota.record_use()
            self.assertFalse(DailyQuota(path, 2, clock=lambda: now[0]).available())  # survives a restart
            self.assertEqual(quota.next_reset(), datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc))
            now[0] = datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc)
            self.assertTrue(quota.available())  # new YouTube quota day
            quota.mark_exhausted()
            self.assertFalse(quota.available())
            self.assertEqual(quota.next_reset(), datetime(2026, 10, 13, 8, 0, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
