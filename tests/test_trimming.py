import json
import unittest

from twitch_auto_clipper.trimming import parse_trims, snap_ends

SENTENCES = [{"start": 10.0 * i, "end": 10.0 * i + 8, "text": f"sentence {i}"} for i in range(12)]


class TrimTests(unittest.TestCase):
    def test_bounds_snap_to_sentences_and_incomplete_moments_are_dropped(self):
        moments = [{"start": 30.0, "end": 40.0}] * 4
        answer = json.dumps({"moments": [
            {"id": "m1", "start": 19.6, "end": 58.3, "complete": True, "reason": "setup then punchline"},
            {"id": "m2", "start": 30, "end": 40, "complete": False},  # needs the rest of the live
            {"id": "m3", "start": 0, "end": 110, "complete": True},  # longer than a Short: keeps its bounds
            {"id": "m4", "start": 30, "end": 38, "complete": True},  # too short: extended to a sentence end
        ]})
        trims = parse_trims(answer, moments, SENTENCES)
        self.assertEqual(trims[0], {"start": 20.0, "end": 58.0, "trim_reason": "setup then punchline"})
        self.assertIsNone(trims[1])
        # Unusable Gemini answer: original end (40.0, mid-sentence) still snaps to a sentence end.
        self.assertEqual(trims[2], {"end": 48.0})
        self.assertEqual((trims[3]["start"], trims[3]["end"]), (30.0, 48.0))
        self.assertEqual(parse_trims("not json", moments, SENTENCES), [{"end": 48.0}] * 4)

    def test_fallback_end_is_left_alone_when_already_on_a_sentence_end(self):
        moments = [{"start": 10.0, "end": 18.0}]
        self.assertEqual(parse_trims("not json", moments, SENTENCES), [{}])

    def test_experiment_max_seconds_allows_longer_shorts(self):
        # gaming_length_v1 (ideal_seconds up to 90s): a 70s answer must not be
        # rejected by the default 58s cap when a higher max_seconds is passed.
        moments = [{"start": 10.0, "end": 20.0}]
        answer = json.dumps({"moments": [
            {"id": "m1", "start": 10, "end": 80, "complete": True, "reason": "long arc"},
        ]})
        trims = parse_trims(answer, moments, SENTENCES, max_seconds=90.0)
        self.assertEqual(trims[0], {"start": 10.0, "end": 78.0, "trim_reason": "long arc"})


    def test_snap_ends_pushes_mid_sentence_ends_forward(self):
        # When Gemini's trim call fails outright, a moment must not keep a raw
        # mid-sentence end: it still snaps to the next sentence boundary.
        moments = [{"start": 30.0, "end": 40.0}, {"start": 10.0, "end": 18.0}]
        snapped = snap_ends(moments, SENTENCES)
        self.assertEqual(snapped[0]["end"], 48.0)
        self.assertEqual(snapped[1], moments[1])  # already on a sentence end: untouched


if __name__ == "__main__":
    unittest.main()
