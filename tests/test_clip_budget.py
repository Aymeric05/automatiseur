import unittest

from twitch_auto_clipper.clip_budget import (
    DEFAULT_CLIP_BUDGET_POLICY,
    ClipBudgetPolicy,
    ClipBudgetTier,
    clip_count_for_stream,
)
from twitch_auto_clipper.twitch_api import LiveStream


class ClipBudgetTests(unittest.TestCase):
    def test_default_policy_covers_each_threshold_and_adjacent_viewer(self) -> None:
        cases = (
            (100_001, 20),
            (100_000, 20),
            (99_999, 15),
            (50_000, 15),
            (49_999, 10),
            (20_000, 10),
            (19_999, 5),
            (10_000, 5),
            (9_999, 2),
            (5_000, 2),
            (4_999, 0),
            (0, 0),
        )
        for viewer_count, expected in cases:
            with self.subTest(viewer_count=viewer_count):
                self.assertEqual(
                    DEFAULT_CLIP_BUDGET_POLICY.clips_for_viewers(viewer_count), expected
                )

    def test_stream_helper_uses_existing_viewer_count(self) -> None:
        stream = LiveStream(
            "stream-1", "broadcaster-1", "login", "Name", 50_000,
            "Title", "Game", "en", "2026-09-25T12:00:00Z",
        )

        self.assertEqual(clip_count_for_stream(stream), 15)

    def test_custom_policy_can_change_thresholds_and_clip_counts(self) -> None:
        policy = ClipBudgetPolicy(
            tiers=(
                ClipBudgetTier(minimum_viewers=1_000, clip_count=8),
                ClipBudgetTier(minimum_viewers=100, clip_count=3),
                ClipBudgetTier(minimum_viewers=0, clip_count=0),
            )
        )

        self.assertEqual(policy.clips_for_viewers(999), 3)
        self.assertEqual(policy.clips_for_viewers(1_000), 8)

    def test_negative_viewer_count_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            DEFAULT_CLIP_BUDGET_POLICY.clips_for_viewers(-1)

    def test_policy_requires_zero_floor_and_descending_thresholds(self) -> None:
        with self.assertRaises(ValueError):
            ClipBudgetPolicy((ClipBudgetTier(100, 1),))
        with self.assertRaises(ValueError):
            ClipBudgetPolicy(
                (
                    ClipBudgetTier(100, 1),
                    ClipBudgetTier(200, 2),
                    ClipBudgetTier(0, 0),
                )
            )


if __name__ == "__main__":
    unittest.main()