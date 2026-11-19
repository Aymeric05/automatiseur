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

    def test_each_channel_is_compared_with_itself_and_only_how_shorts_are_made_counts(self):
        # On a huge channel, "other" still does worse than the channel's usual; on a tiny one, "star" better.
        shorts = [clip(f"h{i}", "huge", 2_000_000, streamer="star") for i in range(6)]
        shorts += [clip(f"o{i}", "huge", 300_000, seconds=50, streamer="other") for i in range(6)]
        shorts += [clip(f"t{i}", "tiny", 5_000, streamer="star") for i in range(6)]
        shorts += [clip(f"u{i}", "tiny", 800, seconds=50, streamer="other") for i in range(6)]
        points = external_points(shorts, "irl")
        self.assertNotIn(("streamer", "star"), points)  # never points for who streamed it
        self.assertGreater(points[("length", "<25s")], 0)  # how it is made: short ones beat their channel
        self.assertLess(points[("length", ">40s")], 0)
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        fresh = PerformanceModel([], "irl", now, external=points)
        self.assertGreater(fresh.points({"seconds": 20}), 0)
    def test_a_channel_that_is_not_a_clip_channel_is_never_read(self):
        import json, tempfile
        from datetime import datetime, timezone
        from pathlib import Path
        from unittest import mock
        from twitch_auto_clipper import competitors
        now = datetime(2026, 11, 20, tzinfo=timezone.utc)
        bad = next(iter(competitors.NOT_CLIP_CHANNELS))
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, competitors.COMPETITORS_FILE).write_text(json.dumps({
                "discovered_at": now.isoformat(), "refreshed_at": "2026-11-01T00:00:00+00:00",
                "channels": {"gaming": ["good", bad], "irl": []}}), encoding="utf-8")
            read = lambda service, channel_id, logins, when: [clip(channel_id, channel_id, 10)]
            with mock.patch.object(competitors, "_recent_shorts", read):
                competitors.refresh_competitors(Path(folder), lambda: None, {"gaming": [], "irl": []}, lambda: now)
            ids = {s["channel_id"] for s in competitors.load_competitor_shorts(Path(folder))}
        self.assertEqual(ids, {"good"})


if __name__ == "__main__":
    unittest.main()
