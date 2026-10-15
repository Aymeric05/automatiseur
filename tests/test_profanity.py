"""Tests for the swear word filter."""

import unittest

from twitch_auto_clipper.profanity import censor, has_slur, profane_intervals


class ProfanityTests(unittest.TestCase):
    def test_swear_words_are_masked_but_ordinary_words_stay(self):
        self.assertEqual(censor("What the fuck, that's bullshit!"), "What the ****, that's ********!")
        self.assertEqual(censor("f***ing hell"), "******* hell")  # Whisper's own censoring
        for clean in ("class", "assassin", "cockpit", "Dickens", "pass the ship", "scunthorpe"):
            self.assertEqual(censor(clean), clean)

    def test_slurs_are_detected(self):
        self.assertTrue(has_slur("you are a retard"))
        self.assertFalse(has_slur("that was a retargeting play"))
        self.assertFalse(has_slur("fuck this"))  # a swear word is not a slur

    def test_muted_moments_are_relative_to_the_clip_start(self):
        segments = [{"words": [
            {"word": " oh", "start": 10.0, "end": 10.3},
            {"word": " fuck!", "start": 10.4, "end": 10.8},
            {"word": " shit", "start": 30.0, "end": 30.4},  # outside the clip
        ]}]
        self.assertEqual(profane_intervals(segments, 10.0, 20.0), [(0.25, 0.95)])
        self.assertEqual(profane_intervals(None, 0.0, 5.0), [])


if __name__ == "__main__":
    unittest.main()
