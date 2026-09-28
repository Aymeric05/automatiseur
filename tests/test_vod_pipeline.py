"""Tests for the end-to-end VOD automation pipeline (all externals mocked)."""

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


def fake_gemini(candidates, transcript, requested_count, model):
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

    def _pipeline(self, upload=True, transcriber=None, ffmpeg=fake_ffmpeg):
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
            uploader=VODShortsUploader(self.tmp, uploader=self._upload) if upload else None,
            output_dir=self.tmp,
        )

    def _manifest(self):
        return json.loads((self.tmp / "vod_1_processing.json").read_text(encoding="utf-8"))

    @patch("twitch_auto_clipper.vod_highlights.select_candidates", side_effect=fake_gemini)
    def test_full_pipeline_publishes_privately_and_cleans_up(self, gemini):
        result = self._pipeline().run(self._acquisition(budget=2))

        self.assertEqual(result.status, "completed", format_vod_automation_result(result))
        gemini.assert_called_once()
        self.assertEqual(gemini.call_args.kwargs["requested_count"], 2)
        self.assertEqual(result.shorts.generated_count, 2)
        self.assertEqual([u.status for u in result.uploads], ["uploaded", "uploaded"])
        self.assertEqual({u["privacy"] for u in self.uploads}, {"private"})
        self.assertTrue(self.uploads[0]["title"].startswith("Streamer: “"))
        self.assertEqual(list(self.tmp.glob("*_short.mp4")), [])  # cleaned after upload
        # Source VOD, transcript and manifest are never deleted.
        self.assertTrue(self.source.is_file())
        self.assertTrue((self.tmp / "vod_1_transcript.json").is_file())
        manifest = self._manifest()
        self.assertEqual(set(manifest["youtube_uploads"]), {"candidate_1", "candidate_2"})
        self.assertIn("candidate_1", manifest["shorts_metadata"])

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
        self.assertEqual(ffmpeg_calls, [])  # uploaded Shorts not regenerated
        self.assertEqual(len(self.uploads), 2)  # no duplicate upload
        self.assertEqual({s.status for s in result.shorts.shorts}, {"already_uploaded"})

    @patch("twitch_auto_clipper.vod_highlights.select_candidates", side_effect=fake_gemini)
    def test_without_uploader_shorts_are_kept_locally(self, gemini):
        result = self._pipeline(upload=False).run(self._acquisition(budget=1))
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.uploads, ())
        self.assertEqual(len(list(self.tmp.glob("*_short.mp4"))), 1)

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
        self.assertEqual(self.uploads, [])

    @patch(
        "twitch_auto_clipper.vod_highlights.select_candidates",
        side_effect=__import__("twitch_auto_clipper.gemini_evaluation", fromlist=["x"]).GeminiEvaluationError("quota"),
    )
    def test_gemini_failure_stops_before_shorts(self, gemini):
        result = self._pipeline().run(self._acquisition())
        self.assertEqual(result.status, "error")
        self.assertIsNone(result.shorts)
        self.assertEqual(list(self.tmp.glob("*_short.mp4")), [])

    @patch("twitch_auto_clipper.vod_highlights.select_candidates", side_effect=fake_gemini)
    def test_failed_upload_keeps_short_and_reports_partial(self, gemini):
        def failing_upload(*args, **kwargs):
            raise RuntimeError("upload interrupted")

        pipeline = self._pipeline()
        pipeline.uploader = VODShortsUploader(self.tmp, uploader=failing_upload)
        result = pipeline.run(self._acquisition(budget=1))

        self.assertEqual(result.status, "partial")
        self.assertEqual(result.uploads[0].status, "error")
        self.assertEqual(len(list(self.tmp.glob("*_short.mp4"))), 1)

    @patch("twitch_auto_clipper.vod_highlights.select_candidates", side_effect=fake_gemini)
    def test_one_ffmpeg_failure_still_uploads_the_other_short(self, gemini):
        def ffmpeg(command):
            if "candidate_1" in command[-1]:
                raise OSError("disk full")
            fake_ffmpeg(command)

        result = self._pipeline(ffmpeg=ffmpeg).run(self._acquisition(budget=2))
        self.assertEqual(result.status, "partial")
        self.assertEqual(result.shorts.status, "partial")
        self.assertEqual([u.candidate_id for u in result.uploads], ["candidate_2"])


class UnfinishedVODTests(unittest.TestCase):
    def test_only_unfinished_vods_with_a_source_are_resumed(self):
        from twitch_auto_clipper.vod_pipeline import find_unfinished_vods

        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            source = tmp / "vod_a.mp4"
            source.write_bytes(b"video")

            def manifest(vod_id, **extra):
                data = {"vod_id": vod_id, "stream_id": f"s_{vod_id}", "clip_budget": 2,
                        "broadcaster_login": "streamer", "broadcaster_name": "Streamer",
                        "source_path": str(source), **extra}
                (tmp / f"{vod_id}_processing.json").write_text(json.dumps(data), encoding="utf-8")

            manifest("vod_a", automation_status="partial")
            manifest("vod_b", automation_status="completed")
            manifest("vod_c", automation_status="error", source_path=str(tmp / "gone.mp4"))
            manifest("vod_d", automation_status="error", clip_budget=0)
            manifest("vod_e")  # interrupted before the end of the pipeline

            resumed = find_unfinished_vods(tmp)

        self.assertEqual([item.vod_id for item in resumed], ["vod_a", "vod_e"])
        self.assertEqual(resumed[0].clip_budget, 2)
        self.assertEqual(resumed[0].broadcaster_name, "Streamer")
        self.assertEqual(resumed[0].status, "already_processed")

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
