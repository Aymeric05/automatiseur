import json
from pathlib import Path
import tempfile
import unittest

from twitch_auto_clipper.audio_events import emotion_moments
from twitch_auto_clipper.gemini_evaluation import _candidate_context
from twitch_auto_clipper.vod_acquisition import VODAcquisitionResult
from twitch_auto_clipper.vod_highlights import new_moments, tag_emotions
from twitch_auto_clipper.vod_processing import VODProcessingPipeline


class EmotionMomentsTests(unittest.TestCase):
    def test_close_frames_make_one_reaction_and_the_longest_wins(self):
        frames = [(100.0, "gasp", 0.5)]  # one loud frame
        frames += [(200.0 + 0.48 * i, "laughter", 0.3) for i in range(8)]  # a laughing fit
        frames += [(203.0, "scream", 0.2)]
        moments = emotion_moments(frames)
        self.assertEqual([moment["emotion"] for moment in moments], ["laughter", "gasp"])
        laugh = moments[0]
        self.assertEqual((laugh["onset"], laugh["start"], laugh["source"]), (200.0, 185.0, "emotion"))
        self.assertAlmostEqual(laugh["score"], 2.6)
        self.assertEqual(moments[1]["start"], 85.0)

    def test_a_long_noise_is_split_and_a_pause_ends_a_reaction(self):
        noise = [(1000.0 + i, "scream", 0.2) for i in range(30)]  # 30 s without a pause
        self.assertEqual(len(emotion_moments(noise)), 2)
        self.assertEqual(len(emotion_moments([(10.0, "gasp", 0.2), (13.0, "gasp", 0.2)])), 2)


class EmotionCandidatesTests(unittest.TestCase):
    def test_only_new_moments_are_added_and_candidates_are_tagged(self):
        candidates = [{"start": 100.0 * i, "end": 100.0 * i + 30} for i in range(1, 7)]
        emotions = [
            {"start": 105.0, "onset": 120.0, "end": 130.0, "emotion": "laughter"},  # covered by a candidate
            {"start": 1000.0, "onset": 1015.0, "end": 1020.0, "emotion": "gasp"},
            {"start": 1005.0, "onset": 1020.0, "end": 1025.0, "emotion": "gasp"},  # same reaction
            {"start": 2000.0, "onset": 2015.0, "end": 2020.0, "emotion": "scream"},
        ]
        self.assertEqual([m["start"] for m in new_moments(emotions, candidates, 5)], [1000.0, 2000.0])
        self.assertEqual([m["start"] for m in new_moments(emotions, candidates, 1)], [1000.0])
        tagged = tag_emotions(candidates, emotions)
        self.assertEqual(tagged[0]["emotion"], "laughter")  # laughs during the 1st candidate
        self.assertNotIn("emotion", tagged[1])
        self.assertEqual(tag_emotions(candidates, []), candidates)


class EmotionProcessingTests(unittest.TestCase):
    def _process(self, root: Path, detector):
        audio = root / "vod-1_audio.mp4"
        audio.write_bytes(b"audio")
        pipeline = VODProcessingPipeline(
            root / "out",
            transcriber=lambda *a, **k: [{"start": 0, "end": 1, "text": "hi"}],
            chat_downloader=lambda url, path: path.write_text('{"comments": []}', encoding="utf-8"),
            emotion_detector=detector,
        )
        result = pipeline.process(VODAcquisitionResult(
            stream_id="s", clip_budget=10, status="downloaded", broadcaster_id="b",
            broadcaster_login="l", broadcaster_name="L", vod_id="vod-1", downloaded_path=audio,
        ))
        manifest = json.loads((root / "out" / "vod-1_processing.json").read_text(encoding="utf-8"))
        return result, manifest

    def test_emotions_are_detected_once_and_a_failure_only_skips_them(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls = []

            def detector(path):
                calls.append(path)
                return [{"start": 1.0, "end": 9.0, "emotion": "laughter"}]

            result, _ = self._process(root, detector)
            self.assertEqual(json.loads(result.emotions_path.read_text(encoding="utf-8"))[0]["emotion"], "laughter")
            self._process(root, detector)
            self.assertEqual(len(calls), 1)

        with tempfile.TemporaryDirectory() as directory:
            def broken(path):
                raise RuntimeError("no model")

            result, manifest = self._process(Path(directory), broken)
            self.assertEqual(result.transcription_status, "completed")
            self.assertEqual(manifest["emotions_error"], "no model")
            self.assertFalse(result.emotions_path.exists())

    def test_gemini_sees_the_emotion_of_a_candidate(self):
        context = _candidate_context(
            [{"start": 0.0, "end": 5.0, "emotion": "laughter"}, {"start": 10.0, "end": 15.0}], []
        )
        self.assertEqual([item["audio_event"] for item in context], ["laughter", None])


if __name__ == "__main__":
    unittest.main()
