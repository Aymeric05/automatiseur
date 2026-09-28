"""Tests for Shorts generation from Gemini-selected VOD highlights."""

from pathlib import Path
import json
import subprocess
import tempfile
import unittest

from twitch_auto_clipper.vod_highlights import VODHighlightSelectionResult
from twitch_auto_clipper.vod_shorts import (
    ShortsGenerationError,
    VODShortsGenerator,
    _build_short_ffmpeg_command,
    _build_vertical_filter_zoomed_out,
    format_vod_shorts_result,
)


def _selection(tmp: Path, selected, status="completed") -> VODHighlightSelectionResult:
    return VODHighlightSelectionResult(
        stream_id="stream_1",
        vod_id="vod_1",
        clip_budget=len(selected),
        candidate_count=len(selected),
        selected=tuple(selected),
        selection_path=tmp / "vod_1_gemini_selection.json",
        candidate_path=tmp / "vod_1_highlights.json",
        status=status,
    )


def _item(index: int, start: float, end: float, score: float = 80.0) -> dict:
    return {
        "candidate_id": f"candidate_{index}",
        "start": start,
        "end": end,
        "score": 4.0,
        "gemini_score": score,
        "gemini_justification": f"Reason {index}",
    }


class FakeFFmpeg:
    """Records commands and writes the output file unless told to fail."""

    def __init__(self, fail_for=(), empty_for=()):
        self.commands = []
        self.fail_for = set(fail_for)
        self.empty_for = set(empty_for)

    def __call__(self, command):
        self.commands.append(command)
        output = Path(command[-1])
        if any(name in output.name for name in self.fail_for):
            raise ShortsGenerationError("FFmpeg a echoue (code 1) : boom")
        output.write_bytes(b"" if any(n in output.name for n in self.empty_for) else b"mp4")


class VODShortsGeneratorTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.source = self.tmp / "vod_1.mp4"
        self.source.write_bytes(b"source video")

    def tearDown(self):
        self._tmp.cleanup()

    def _generator(self, ffmpeg, duration=600.0):
        return VODShortsGenerator(
            output_dir=self.tmp,
            ffmpeg_runner=ffmpeg,
            duration_probe=lambda _path: duration,
        )

    def test_generates_one_short_per_selection_with_margins(self):
        ffmpeg = FakeFFmpeg()
        result = self._generator(ffmpeg).generate(
            _selection(self.tmp, [_item(1, 20, 30), _item(2, 100, 110)]), self.source
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.generated_count, 2)
        first = result.shorts[0]
        # Default margins are a short breath: candidates are already sentence-aligned.
        self.assertEqual((first.start, first.end), (19.5, 31.0))
        self.assertEqual((first.candidate_start, first.candidate_end), (20.0, 30.0))
        self.assertEqual(first.gemini_score, 80.0)
        self.assertEqual(first.gemini_justification, "Reason 1")
        self.assertTrue(first.output_path.is_file())
        self.assertEqual(first.output_path.name, "vod_1_candidate_1_short.mp4")
        self.assertEqual(len(ffmpeg.commands), 2)

    def test_margins_are_clamped_to_the_vod_limits(self):
        result = self._generator(FakeFFmpeg(), duration=32.0).generate(
            _selection(self.tmp, [_item(1, 0.2, 31.5)]), self.source
        )
        self.assertEqual((result.shorts[0].start, result.shorts[0].end), (0.0, 32.0))

    def test_highlight_sentence_is_kept_as_the_candidate_moment(self):
        item = {**_item(1, 40, 60), "highlight_start": 44.0, "highlight_end": 47.5}
        short = self._generator(FakeFFmpeg()).generate(_selection(self.tmp, [item]), self.source).shorts[0]
        self.assertEqual((short.start, short.end), (39.5, 61.0))
        self.assertEqual((short.candidate_start, short.candidate_end), (44.0, 47.5))

    def test_existing_valid_short_is_not_regenerated(self):
        (self.tmp / "vod_1_candidate_1_short.mp4").write_bytes(b"already here")
        ffmpeg = FakeFFmpeg()
        result = self._generator(ffmpeg).generate(
            _selection(self.tmp, [_item(1, 20, 30)]), self.source
        )
        self.assertEqual(result.shorts[0].status, "already_exists")
        self.assertEqual(ffmpeg.commands, [])

    def test_empty_existing_short_is_regenerated(self):
        (self.tmp / "vod_1_candidate_1_short.mp4").write_bytes(b"")
        ffmpeg = FakeFFmpeg()
        result = self._generator(ffmpeg).generate(
            _selection(self.tmp, [_item(1, 20, 30)]), self.source
        )
        self.assertEqual(result.shorts[0].status, "generated")
        self.assertEqual(len(ffmpeg.commands), 1)

    def test_already_uploaded_short_is_not_regenerated(self):
        manifest = {"youtube_uploads": {"candidate_1": {"video_id": "yt1"}}}
        (self.tmp / "vod_1_processing.json").write_text(json.dumps(manifest), encoding="utf-8")
        ffmpeg = FakeFFmpeg()
        result = self._generator(ffmpeg).generate(
            _selection(self.tmp, [_item(1, 20, 30)]), self.source
        )
        self.assertEqual(result.shorts[0].status, "already_uploaded")
        self.assertEqual(result.status, "completed")
        self.assertEqual(ffmpeg.commands, [])

    def test_ffmpeg_failure_on_one_clip_does_not_stop_the_others(self):
        ffmpeg = FakeFFmpeg(fail_for={"candidate_1"})
        result = self._generator(ffmpeg).generate(
            _selection(self.tmp, [_item(1, 20, 30), _item(2, 100, 110)]), self.source
        )
        self.assertEqual(result.status, "partial")
        self.assertEqual([s.status for s in result.shorts], ["error", "generated"])
        self.assertIn("boom", result.shorts[0].error)
        self.assertFalse(result.shorts[0].output_path.exists())
        self.assertEqual(list(self.tmp.glob("*.tmp.mp4")), [])

    def test_raw_called_process_error_is_handled_per_clip(self):
        def ffmpeg(command):
            raise subprocess.CalledProcessError(1, command)

        result = self._generator(ffmpeg).generate(
            _selection(self.tmp, [_item(1, 20, 30)]), self.source
        )
        self.assertEqual(result.status, "failed")

    def test_empty_ffmpeg_output_is_an_error(self):
        result = self._generator(FakeFFmpeg(empty_for={"candidate_1"})).generate(
            _selection(self.tmp, [_item(1, 20, 30)]), self.source
        )
        self.assertEqual(result.shorts[0].status, "error")
        self.assertEqual(result.status, "failed")
        self.assertFalse(result.shorts[0].output_path.exists())

    def test_all_clips_failing_is_failed_not_partial(self):
        result = self._generator(FakeFFmpeg(fail_for={"candidate"})).generate(
            _selection(self.tmp, [_item(1, 20, 30), _item(2, 100, 110)]), self.source
        )
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.generated_count, 0)
        self.assertEqual(result.error_count, 2)

    def test_empty_selection_is_empty_and_runs_nothing(self):
        ffmpeg = FakeFFmpeg()
        result = self._generator(ffmpeg).generate(_selection(self.tmp, []), self.source)
        self.assertEqual(result.status, "empty")
        self.assertEqual(ffmpeg.commands, [])

    def test_invalid_timestamps_are_reported_per_clip(self):
        bad = {"candidate_id": "candidate_1", "start": 50, "end": 40}
        result = self._generator(FakeFFmpeg()).generate(
            _selection(self.tmp, [bad, _item(2, 100, 110)]), self.source
        )
        self.assertEqual([s.status for s in result.shorts], ["error", "generated"])
        self.assertEqual(result.status, "partial")

    def test_missing_or_empty_source_raises(self):
        self.source.write_bytes(b"")
        with self.assertRaises(ShortsGenerationError):
            self._generator(FakeFFmpeg()).generate(
                _selection(self.tmp, [_item(1, 20, 30)]), self.source
            )

    def test_error_selection_is_rejected(self):
        with self.assertRaises(ShortsGenerationError):
            self._generator(FakeFFmpeg()).generate(
                _selection(self.tmp, [], status="error"), self.source
            )

    def test_manifest_keeps_candidate_context(self):
        self._generator(FakeFFmpeg(fail_for={"candidate_2"})).generate(
            _selection(self.tmp, [_item(1, 20, 30, score=91), _item(2, 100, 110)]),
            self.source,
        )
        manifest = json.loads((self.tmp / "vod_1_processing.json").read_text(encoding="utf-8"))
        entry = manifest["generated_shorts"]["candidate_1"]
        self.assertEqual(entry["file"], "vod_1_candidate_1_short.mp4")
        self.assertEqual((entry["candidate_start"], entry["candidate_end"]), (20.0, 30.0))
        self.assertEqual(entry["gemini_score"], 91)
        self.assertEqual(entry["gemini_justification"], "Reason 1")
        self.assertIn("candidate_2", manifest["shorts_errors"])

    def test_subtitles_are_burned_from_transcript_and_cleaned_up(self):
        transcript = self.tmp / "transcript.json"
        transcript.write_text(json.dumps([{
            "start": 20.0, "end": 22.0, "text": "no way",
            "words": [
                {"start": 20.0, "end": 20.5, "word": "no"},
                {"start": 20.5, "end": 21.0, "word": "way"},
            ],
        }]), encoding="utf-8")
        ffmpeg = FakeFFmpeg()
        result = self._generator(ffmpeg).generate(
            _selection(self.tmp, [_item(1, 20, 30)]), self.source, transcript
        )
        self.assertTrue(result.shorts[0].subtitles)
        self.assertIn("subtitles=", ffmpeg.commands[0][ffmpeg.commands[0].index("-vf") + 1])
        self.assertEqual(list(self.tmp.glob("*.ass")), [])

    def test_invalid_subtitles_fall_back_to_a_short_without_them(self):
        transcript = self.tmp / "transcript.json"
        transcript.write_text(json.dumps([{"start": 20, "end": 22, "words": [{"bad": 1}]}]), encoding="utf-8")
        ffmpeg = FakeFFmpeg()
        result = self._generator(ffmpeg).generate(
            _selection(self.tmp, [_item(1, 20, 30)]), self.source, transcript
        )
        short = result.shorts[0]
        self.assertEqual(short.status, "generated")
        self.assertFalse(short.subtitles)
        self.assertIn("sous-titres ignores", short.warning)

    def test_format_lists_each_clip(self):
        result = self._generator(FakeFFmpeg(fail_for={"candidate_2"})).generate(
            _selection(self.tmp, [_item(1, 20, 30), _item(2, 100, 110)]), self.source
        )
        lines = format_vod_shorts_result(result)
        self.assertIn("1/2", lines[0])
        self.assertIn("[erreur] candidate_2", lines[2])


class VerticalFilterTests(unittest.TestCase):
    def test_filter_is_centered_slightly_zoomed_out_and_padded(self):
        vertical_filter = _build_vertical_filter_zoomed_out(Path("any.mp4"))
        self.assertIn("scale=-2:1920", vertical_filter)
        self.assertIn("crop='min(iw,1160)':ih", vertical_filter)  # 1080 + 80 px
        self.assertIn("pad=1080:1920", vertical_filter)
        self.assertNotIn(":0,scale", vertical_filter)  # no focus-offset crop

    def test_command_writes_mp4_with_filter_and_optional_subtitles(self):
        command = _build_short_ffmpeg_command(
            Path("in.mp4"), Path("out.tmp.mp4"), 10.0, 25.0, "FILTER", Path("subs.ass")
        )
        self.assertEqual(command[command.index("-t") + 1], "15.0")
        self.assertTrue(command[command.index("-vf") + 1].startswith("FILTER,subtitles="))
        self.assertEqual(command[command.index("-f") + 1], "mp4")
        self.assertEqual(command[-1], "out.tmp.mp4")


if __name__ == "__main__":
    unittest.main()
