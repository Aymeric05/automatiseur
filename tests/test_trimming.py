import json
import unittest

from twitch_auto_clipper.trimming import parse_trims

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
        self.assertEqual(trims[2], {})
        self.assertEqual((trims[3]["start"], trims[3]["end"]), (30.0, 48.0))
        self.assertEqual(parse_trims("not json", moments, SENTENCES), [{}] * 4)


if __name__ == "__main__":
    unittest.main()
