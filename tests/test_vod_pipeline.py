"""Tests for the end-to-end VOD automation pipeline (all externals mocked)."""

from dataclasses import replace
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from twitch_auto_clipper.shorts_upload import VODShortsUploader
from twitch_auto_clipper.vod_acquisition import VODAcquisitionResult
from twitch_auto_clipper.vod_highlights import VODHighlightSelector
from twitch_auto_clipper.vod_pipeline import VODAutomationPipeline, format_vod_automation_result
from twitch_auto_clipper.vod_processing import VODProcessingPipeline
from twitch_auto_clipper.vod_shorts import VODShortsGenerator

TRANSCRIPT = [
    {
        "start": 20.0, "end": 24.0, "text": "No way! Insane clip!",
        "words": [
            {"start": 20.0, "end": 20.5, "word": "No"},
            {"start": 20.5, "end": 21.0, "word": "way!"},
            {"start": 21.0, "end": 22.0, "word": "Insane"},
            {"start": 22.0, "end": 23.0, "word": "clip!"},
        ],
    },
    {"start": 100.0, "end": 104.0, "text": "Let's go! Amazing!"},
]


def fake_gemini(candidates, transcript, requested_count, model, **options):
    return [
        {"candidate_id": f"candidate_{i}", "interesting": True, "score": 90 - i,
         "justification": f"why {i}"}
        for i in range(1, requested_count + 1)
    ]


def fake_ffmpeg(command):
    Path(command[-1]).write_bytes(b"mp4")


class VODAutomationPipelineTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.source = self.tmp / "vod_1.mp4"
        self.source.write_bytes(b"source video")
        self.transcriptions = 0
        self.uploads = []

    def tearDown(self):
        self._tmp.cleanup()

    def _acquisition(self, budget=2, source=None, status="downloaded"):
        return VODAcquisitionResult(
            stream_id="stream_1", clip_budget=budget, status=status,
            broadcaster_id="b1", broadcaster_login="streamer", broadcaster_name="Streamer",
            vod_id="vod_1", downloaded_path=source or self.source,
        )

    def _transcriber(self, path, **kwargs):
        self.transcriptions += 1
        return TRANSCRIPT

    def _upload(self, path, title, description, privacy, *args, **kwargs):
        self.uploads.append({"path": path, "title": title, "privacy": privacy})
        return f"yt{len(self.uploads)}", f"https://youtu.be/yt{len(self.uploads)}"

    def _pipeline(self, transcriber=None, ffmpeg=fake_ffmpeg):
        def no_chat(url, path):
            raise OSError("TwitchDownloaderCLI missing")

        return VODAutomationPipeline(
            processing_pipeline=VODProcessingPipeline(
                self.tmp, transcriber=transcriber or self._transcriber, chat_downloader=no_chat
            ),
            highlight_selector=VODHighlightSelector(self.tmp),
            shorts_generator=VODShortsGenerator(
                self.tmp, ffmpeg_runner=ffmpeg, duration_probe=lambda _p: 600.0
            ),
            output_dir=self.tmp,
        )

    def _manifest(self):
        return json.loads((self.tmp / "vod_1_processing.json").read_text(encoding="utf-8"))

    @patch("twitch_auto_clipper.vod_highlights.select_candidates", side_effect=fake_gemini)
    def test_full_pipeline_leaves_shorts_and_metadata_ready_to_publish(self, gemini):
        result = self._pipeline().run(self._acquisition(budget=2))

        self.assertEqual(result.status, "completed", format_vod_automation_result(result))
        gemini.assert_called_once()
        self.assertEqual(gemini.call_args.kwargs["requested_count"], 2)
        self.assertEqual(result.shorts.generated_count, 2)
        self.assertEqual(len(list(self.tmp.glob("*_short.mp4"))), 2)  # waiting for publication
        self.assertTrue(self.source.is_file())
        self.assertTrue((self.tmp / "vod_1_transcript.json").is_file())
        manifest = self._manifest()
        keys = {short.key for short in result.shorts.shorts}
        self.assertEqual(set(manifest["generated_shorts"]), keys)
        self.assertEqual(set(manifest["shorts_metadata"]), keys)
        self.assertEqual(manifest["automation_status"], "completed")

    def _render_with_focus(self, focus, game_name=""):
        commands = []

        def ffmpeg(command):
            commands.append(" ".join(command))
            fake_ffmpeg(command)

        pipeline = self._pipeline(ffmpeg=ffmpeg)
        pipeline.focus_finder = focus
        result = pipeline.run(replace(self._acquisition(budget=2), game_name=game_name))
        self.assertEqual(result.status, "completed", format_vod_automation_result(result))
        return commands

    @patch("twitch_auto_clipper.vod_highlights.select_candidates", side_effect=fake_gemini)
    def test_screen_shorts_are_centered_on_what_matters(self, gemini):
        asked = []

        def focus(vod_id, times):
            asked.append((vod_id, len(times)))
            return [0.27, None]  # the second one is filmed with a camera

        commands = self._render_with_focus(focus)
        self.assertEqual(asked, [("vod_1", 2)])
        self.assertEqual(sum("0.270*iw-ow/2" in command for command in commands), 1)
        focus = [short["focus_x"] for short in self._manifest()["generated_shorts"].values()]
        self.assertEqual(sorted(focus, key=str), [0.27, None])

    @patch("twitch_auto_clipper.vod_highlights.select_candidates", side_effect=fake_gemini)
    def test_shorts_stay_centered_when_the_focus_is_unknown_or_the_stream_is_irl(self, gemini):
        def broken(vod_id, times):
            raise RuntimeError("Gemini unavailable")

        self.assertFalse(any("iw-ow/2" in command for command in self._render_with_focus(broken)))
        for path in self.tmp.glob("vod_1_*"):
            path.unlink()
        asked = []
        self._render_with_focus(lambda vod_id, times: asked.append(times) or [0.27] * len(times), "IRL")
        self.assertEqual(asked, [])

    @patch("twitch_auto_clipper.vod_highlights.select_candidates", side_effect=fake_gemini)
    def test_completed_vod_shorts_are_published_best_score_first_then_cleaned_up(self, gemini):
        self._pipeline().run(self._acquisition(budget=2))
        uploader = VODShortsUploader(self.tmp, uploader=self._upload)

        vod_id, first = uploader.publish_next()
        self.assertEqual((vod_id, first.candidate_id, first.status), ("vod_1", "candidate_1", "uploaded"))
        self.assertEqual(uploader.publish_next()[1].candidate_id, "candidate_2")  # score 88 < 89
        self.assertIsNone(uploader.publish_next())  # nothing left
        self.assertEqual(list(self.tmp.glob("*_short.mp4")), [])
        self.assertEqual({u["privacy"] for u in self.uploads}, {"private"})
        self.assertTrue(self.uploads[0]["title"].startswith("Streamer: “"))
        self.assertEqual(set(self._manifest()["youtube_uploads"]), set(self._manifest()["generated_shorts"]))

        rerun = self._pipeline().run(self._acquisition(budget=2))  # a rerun never re-renders them
        self.assertEqual({s.status for s in rerun.shorts.shorts}, {"already_uploaded"})
        self.assertIsNone(uploader.publish_next())

    @patch("twitch_auto_clipper.vod_highlights.select_candidates", side_effect=fake_gemini)
    def test_rerun_resumes_without_redoing_finished_work(self, gemini):
        self._pipeline().run(self._acquisition(budget=2))
        ffmpeg_calls = []

        def counting_ffmpeg(command):
            ffmpeg_calls.append(command)
            fake_ffmpeg(command)

        result = self._pipeline(ffmpeg=counting_ffmpeg).run(self._acquisition(budget=2))

        self.assertEqual(result.status, "completed")
        self.assertEqual(self.transcriptions, 1)
        self.assertEqual(gemini.call_count, 1)  # selection file reused
        self.assertEqual(ffmpeg_calls, [])  # existing Shorts not regenerated
        self.assertEqual({s.status for s in result.shorts.shorts}, {"already_exists"})

    @patch("twitch_auto_clipper.vod_highlights.select_candidates")
    def test_moments_gemini_finds_uninteresting_are_never_rendered(self, gemini):
        def mixed(candidates, transcript, requested_count, model, **options):
            return [
                {"candidate_id": "candidate_1", "interesting": True, "score": 80, "justification": "Drole."},
                {"candidate_id": "candidate_2", "interesting": False, "score": 20, "justification": "Plat."},
            ]

        gemini.side_effect = mixed
        result = self._pipeline().run(self._acquisition(budget=2))
        self.assertEqual(result.status, "completed")
        self.assertEqual([short.candidate_id for short in result.shorts.shorts], ["candidate_1"])
        self.assertEqual(len(list(self.tmp.glob("*_short.mp4"))), 1)

        gemini.side_effect = lambda *a, **k: [
            {"candidate_id": "candidate_1", "interesting": False, "score": 10, "justification": "Rien."},
        ]
        (self.tmp / "vod_2_audio.mp4").write_bytes(b"audio")
        boring = VODAcquisitionResult(
            stream_id="stream_2", clip_budget=1, status="downloaded", broadcaster_id="b1",
            broadcaster_login="streamer", broadcaster_name="Streamer", vod_id="vod_2",
            downloaded_path=self.tmp / "vod_2_audio.mp4",
        )
        pipeline = self._pipeline()
        pipeline.delete_sources_on_success = True
        result = pipeline.run(boring)
        self.assertEqual((result.status, result.shorts), ("completed", None))
        self.assertIn("interessant", result.message)
        self.assertFalse((self.tmp / "vod_2_audio.mp4").exists())  # nothing kept for a dull VOD

    @patch("twitch_auto_clipper.vod_highlights.select_candidates")
    def test_moments_below_the_minimum_score_are_never_rendered(self, gemini):
        gemini.side_effect = lambda *a, **k: [
            {"candidate_id": "candidate_1", "interesting": True, "score": 60, "justification": "Ok."},
            {"candidate_id": "candidate_2", "interesting": True, "score": 59, "justification": "Moyen."},
        ]
        result = self._pipeline().run(self._acquisition(budget=2))
        self.assertEqual([short.candidate_id for short in result.shorts.shorts], ["candidate_1"])

    @patch("twitch_auto_clipper.vod_highlights.select_candidates", side_effect=fake_gemini)
    def test_a_moment_with_a_slur_is_never_rendered(self, gemini):
        slur = [{"start": 100.0, "end": 104.0, "text": "You retard!",
                 "words": [{"start": 100.0, "end": 100.5, "word": "You"},
                           {"start": 100.5, "end": 101.0, "word": "retard!"}]}]
        pipeline = self._pipeline(transcriber=lambda path, **kwargs: TRANSCRIPT[:1] + slur)
        result = pipeline.run(self._acquisition(budget=2))
        texts = [short.candidate_start for short in result.shorts.shorts]
        self.assertTrue(texts and all(start < 50 for start in texts))  # only the clean moment

    @patch("twitch_auto_clipper.vod_highlights.select_candidates", side_effect=fake_gemini)
    def test_zero_budget_skips_everything(self, gemini):
        result = self._pipeline().run(self._acquisition(budget=0))
        self.assertEqual(result.status, "skipped")
        gemini.assert_not_called()
        self.assertEqual(self.transcriptions, 0)

    @patch("twitch_auto_clipper.vod_highlights.select_candidates", side_effect=fake_gemini)
    def test_invalid_vod_skips_everything(self, gemini):
        empty = self.tmp / "empty.mp4"
        empty.write_bytes(b"")
        for acquisition in (
            self._acquisition(source=empty),
            self._acquisition(source=self.tmp / "missing.mp4"),
            self._acquisition(status="vod_not_available"),
        ):
            self.assertEqual(self._pipeline().run(acquisition).status, "skipped")
        gemini.assert_not_called()

    @patch("twitch_auto_clipper.vod_highlights.select_candidates", side_effect=fake_gemini)
    def test_transcription_failure_stops_before_gemini(self, gemini):
        def broken(path, **kwargs):
            raise RuntimeError("whisper crashed")

        result = self._pipeline(transcriber=broken).run(self._acquisition())
        self.assertEqual(result.status, "error")
        gemini.assert_not_called()

    @patch(
        "twitch_auto_clipper.vod_highlights.select_candidates",
        side_effect=__import__("twitch_auto_clipper.gemini_evaluation", fromlist=["x"]).GeminiEvaluationError("Gemini a retourne un JSON invalide."),
    )
    def test_gemini_failure_stops_before_shorts(self, gemini):
        result = self._pipeline().run(self._acquisition())
        self.assertEqual(result.status, "error")
        self.assertIsNone(result.shorts)
        self.assertEqual(list(self.tmp.glob("*_short.mp4")), [])

    @patch(
        "twitch_auto_clipper.vod_highlights.select_candidates",
        side_effect=__import__("twitch_auto_clipper.gemini_evaluation", fromlist=["x"]).GeminiEvaluationError(
            "Echec de l'appel Gemini : Error code: 429 - Your project has exceeded a quota."
        ),
    )
    def test_gemini_quota_is_a_wait_not_a_failure(self, gemini):
        result = self._pipeline().run(self._acquisition())
        self.assertEqual(result.status, "waiting_gemini")
        self.assertIsNotNone(result.retry_at)
        self.assertIsNone(result.shorts)

    def test_gemini_retry_time_follows_googles_retry_delay(self):
        from datetime import datetime, timezone

        from twitch_auto_clipper.vod_pipeline import _gemini_retry_at

        now = datetime.now(timezone.utc)
        quota = _gemini_retry_at("429 RESOURCE_EXHAUSTED ... 'retryDelay': '17458s'")
        self.assertAlmostEqual((quota - now).total_seconds(), 17458 + 60, delta=5)
        overloaded = _gemini_retry_at("503 UNAVAILABLE. This model is currently experiencing high demand.")
        self.assertAlmostEqual((overloaded - now).total_seconds(), 1800, delta=5)
        self.assertIsNone(_gemini_retry_at("Gemini a retourne un JSON invalide."))

    @patch("twitch_auto_clipper.vod_highlights.select_candidates", side_effect=fake_gemini)
    def test_one_ffmpeg_failure_keeps_the_other_short_but_waits_for_a_retry(self, gemini):
        calls = []

        def ffmpeg(command):
            calls.append(command)
            if len(calls) == 1:
                raise OSError("disk full")
            fake_ffmpeg(command)

        result = self._pipeline(ffmpeg=ffmpeg).run(self._acquisition(budget=2))
        self.assertEqual(result.status, "partial")
        self.assertEqual(result.shorts.status, "partial")
        self.assertEqual(len(list(self.tmp.glob("*_short.mp4"))), 1)
        # Not completed yet: nothing of this VOD is published before the retry.
        self.assertIsNone(VODShortsUploader(self.tmp, uploader=self._upload).publish_next())

    @patch("twitch_auto_clipper.vod_highlights.select_candidates", side_effect=fake_gemini)
    def test_youtube_quota_refusal_closes_the_upload_day(self, gemini):
        def refused(*args, **kwargs):
            raise RuntimeError('<HttpError 403 "reason": "quotaExceeded">')

        from datetime import datetime, timezone

        self._pipeline().run(self._acquisition(budget=1))
        uploader = VODShortsUploader(
            self.tmp, uploader=refused, daily_upload_limit=6, random_source=lambda: 0.0, min_reserve=1,
            clock=lambda: datetime(2026, 10, 14, 7, 30, tzinfo=timezone.utc),  # publication hour
        )

        self.assertEqual(uploader.publish_next()[1].status, "deferred")
        self.assertFalse(uploader.quota.available())  # no more tries today
        self.assertIsNone(uploader.publish_next())
        self.assertNotIn("youtube_upload_errors", self._manifest())
        self.assertEqual(len(list(self.tmp.glob("*_short.mp4"))), 1)  # kept for tomorrow

    @patch("twitch_auto_clipper.vod_highlights.select_candidates", side_effect=fake_gemini)
    def test_completed_vod_keeps_only_its_shorts_and_manifest(self, gemini):
        audio = self.tmp / "vod_1_audio.mp4"
        audio.write_bytes(b"audio")
        leftover = self.tmp / "vod_1_audio.mp4.part-Frag12.part"  # an interrupted download
        leftover.write_bytes(b"part")
        (self.tmp / "vod_1_chat.json").write_text('{"comments": []}', encoding="utf-8")
        sources = []
        pipeline = self._pipeline()
        pipeline.video_source = lambda acquisition: sources.append(acquisition) or self.source
        pipeline.delete_sources_on_success = True

        result = pipeline.run(self._acquisition(budget=1, source=audio))

        self.assertEqual(result.status, "completed")
        self.assertEqual(len(sources), 1)  # the Shorts read the video source, not the audio
        self.assertFalse(audio.exists())
        self.assertFalse(leftover.exists())
        self.assertEqual(
            sorted(path.name for path in self.tmp.iterdir() if path.name.startswith("vod_1_")),
            sorted(["vod_1_processing.json", *(p.name for p in self.tmp.glob("*_short.mp4"))]),
        )  # unpublished Short and manifest only
        self.assertIn("vod_1_audio.mp4", self._manifest()["deleted_sources"])
        self.assertIn("title", next(iter(self._manifest()["shorts_metadata"].values())))

    @patch("twitch_auto_clipper.vod_highlights.select_candidates", side_effect=fake_gemini)
    def test_unfinished_vod_keeps_its_sources(self, gemini):
        audio = self.tmp / "vod_1_audio.mp4"
        audio.write_bytes(b"audio")

        def broken_ffmpeg(command):
            raise OSError("disk full")

        pipeline = self._pipeline(ffmpeg=broken_ffmpeg)
        pipeline.delete_sources_on_success = True
        pipeline.video_source = lambda acquisition: self.source

        self.assertEqual(pipeline.run(self._acquisition(budget=1, source=audio)).status, "partial")
        self.assertTrue(audio.is_file())


class DueVODWorkerTests(unittest.TestCase):
    def test_worker_runs_each_ready_job_and_reports_its_outcome(self):
        from unittest.mock import Mock

        from twitch_auto_clipper.vod_pipeline import process_due_vods

        ready = VODAcquisitionResult("s1", 2, "downloaded", "b", "login", "Name", "v1", Path("v1_audio.mp4"))
        waiting = VODAcquisitionResult("s2", 2, "vod_not_available", "b", "login", "Name")
        manager = Mock()
        manager.input_dir = manager_dir = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, manager_dir)
        manager.active_vod_ids.return_value = set()
        manager.acquire_due.return_value = iter([ready, waiting])
        manager.record_automation.return_value = "retry"
        automation = Mock()
        automation.output_dir = manager_dir
        automation.run.side_effect = RuntimeError("bug")  # must not stop the worker
        lines = []

        count = process_due_vods(manager, automation, lambda line, error: lines.append((line, error)))

        self.assertEqual(count, 2)
        automation.run.assert_called_once_with(ready)  # the unavailable VOD is not processed
        manager.record_automation.assert_called_once()
        self.assertEqual(manager.record_automation.call_args.args[:3], ("s1", "v1", "error"))
        self.assertTrue(any("nouvel essai" in line for line, error in lines))


class NearDuplicateTests(unittest.TestCase):
    def test_overlapping_moments_keep_only_the_best(self):
        from twitch_auto_clipper.vod_pipeline import without_near_duplicates

        moments = [
            {"start": 100.0, "end": 130.0, "gemini_score": 70},
            {"start": 110.0, "end": 140.0, "gemini_score": 90},  # same scene, better
            {"start": 300.0, "end": 330.0, "gemini_score": 60},
        ]
        kept = without_near_duplicates(moments)
        self.assertEqual([m["gemini_score"] for m in kept], [90, 60])


class CleanupTests(unittest.TestCase):
    def test_only_finished_vods_lose_their_files(self):
        from twitch_auto_clipper.vod_pipeline import cleanup_finished_vods

        with tempfile.TemporaryDirectory() as directory:
            input_dir, output_dir = Path(directory, "input"), Path(directory, "output")
            input_dir.mkdir()
            output_dir.mkdir()
            names = {
                input_dir: ["1_audio.mp4", "2_audio.mp4.part", "3_audio.mp4", "demo.mp4"],
                output_dir: ["1_transcript.json", "1_processing.json", "2_processing.json",
                             "3_transcript.json", "4_0.0-5.0_short.mp4",
                             "5_processing.json", "5_0.0-5.0_short.mp4", "monitor.log"],
            }
            for folder, files in names.items():
                for name in files:
                    (folder / name).write_bytes(b"x")
            # 4 is completed: its Short is in the reserve. 5 failed: its Short is never published.
            (output_dir / "4_processing.json").write_text('{"automation_status": "completed"}', encoding="utf-8")

            done = cleanup_finished_vods(input_dir, output_dir, active_vod_ids={"3"})

            self.assertEqual(sorted(done), ["1", "2", "5"])
            remaining = sorted(p.name for p in [*input_dir.iterdir(), *output_dir.iterdir()])
            self.assertEqual(remaining, [
                "3_audio.mp4", "3_transcript.json",  # job still queued
                "4_0.0-5.0_short.mp4", "4_processing.json",  # Short in the reserve
                "demo.mp4", "monitor.log",  # not VOD files
            ])


class StaleTemporaryFilesTests(unittest.TestCase):
    def test_temporary_files_of_a_cut_run_go_after_six_hours(self):
        import os
        import time

        from twitch_auto_clipper.vod_pipeline import cleanup_finished_vods

        with tempfile.TemporaryDirectory() as directory:
            input_dir, output_dir = Path(directory, "input"), Path(directory, "output")
            (output_dir / "tmp" / "tmpabc").mkdir(parents=True)
            input_dir.mkdir()
            old = [input_dir / "7_audio.mp4.part", input_dir / "7_audio.mp4.ytdl",
                   output_dir / "7_1.0-20.0_short.tmp.mp4", output_dir / "7_1.0-20.0_short_hook.png"]
            fresh = input_dir / "8_audio.mp4.part"  # a download in progress
            mine = input_dir / "my_video.part.mp4"  # a file the user put there: never touched
            for path in [*old, fresh, mine]:
                path.write_bytes(b"x")
            seven_hours_ago = time.time() - 7 * 3600
            for path in [*old, mine, output_dir / "tmp" / "tmpabc"]:
                os.utime(path, (seven_hours_ago, seven_hours_ago))

            cleanup_finished_vods(input_dir, output_dir, active_vod_ids={"7", "8"})

            self.assertFalse(any(path.exists() for path in old))
            self.assertFalse((output_dir / "tmp" / "tmpabc").exists())
            self.assertTrue(fresh.exists())
            self.assertTrue(mine.exists())


class ManifestStatusTests(unittest.TestCase):
    @patch("twitch_auto_clipper.vod_highlights.select_candidates", side_effect=fake_gemini)
    def test_run_records_the_final_status_in_the_manifest(self, gemini):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            source = tmp / "vod_1.mp4"
            source.write_bytes(b"video")
            pipeline = VODAutomationPipeline(
                processing_pipeline=VODProcessingPipeline(
                    tmp, transcriber=lambda *a, **k: TRANSCRIPT,
                    chat_downloader=lambda *a: (_ for _ in ()).throw(OSError("no chat")),
                ),
                highlight_selector=VODHighlightSelector(tmp),
                shorts_generator=VODShortsGenerator(
                    tmp, ffmpeg_runner=fake_ffmpeg, duration_probe=lambda _p: 600.0
                ),
                output_dir=tmp,
            )
            pipeline.run(VODAcquisitionResult(
                "stream_1", 1, "downloaded", "b", "streamer", "Streamer", "vod_1", source
            ))
            manifest = json.loads((tmp / "vod_1_processing.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["automation_status"], "completed")


if __name__ == "__main__":
    unittest.main()
