import unittest

from twitch_auto_clipper.competitors import _seconds, find_streamer
from twitch_auto_clipper.performance import PerformanceModel, external_points


def clip(video, channel, views, seconds=20, streamer=None):
    return {"video_id": video, "channel_id": channel, "theme": "irl", "views": views,
            "seconds": seconds, "streamer": streamer, "title": video}


class CompetitorTests(unittest.TestCase):
    def test_streamers_are_found_in_titles_and_durations_read(self):
        logins = ["kaicenat", "kai", "maya", "stableronaldo"]
        self.assertEqual(find_streamer("Kai Cenat Feels Siebe's Aura", logins), "kaicenat")
        self.assertEqual(find_streamer("Stable Ronaldo gets caught", logins), "stableronaldo")
        self.assertIsNone(find_streamer("A trip to Malaysia", logins))  # short login: whole words only
        self.assertEqual(find_streamer("maya reacts", logins), "maya")
        self.assertEqual((_seconds("PT45S"), _seconds("PT1M3S"), _seconds("P0D")), (45, 63, 0))

    def test_each_channel_is_compared_with_itself_and_its_points_fade_with_own_results(self):
        # On a huge channel, "other" still does worse than the channel's usual; on a tiny one, "star" better.
        shorts = [clip(f"h{i}", "huge", 2_000_000, streamer="star") for i in range(6)]
        shorts += [clip(f"o{i}", "huge", 300_000, seconds=50, streamer="other") for i in range(6)]
        shorts += [clip(f"t{i}", "tiny", 5_000, streamer="star") for i in range(6)]
        shorts += [clip(f"u{i}", "tiny", 800, seconds=50, streamer="other") for i in range(6)]
        points = external_points(shorts, "irl")
        self.assertGreater(points[("streamer", "star")], 0)
        self.assertLess(points[("streamer", "other")], 0)  # 300,000 views, yet below its channel's usual
        self.assertGreater(points[("length", "<25s")], points[("length", ">40s")])
        self.assertLessEqual(abs(points[("streamer", "star")]), 1.0)
        fresh = PerformanceModel([], "irl", __import__("datetime").datetime.now(__import__("datetime").timezone.utc), external=points)
        self.assertGreater(fresh.points({"streamer": "star"}), 0)


if __name__ == "__main__":
    unittest.main()
