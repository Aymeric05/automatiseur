from datetime import datetime, timedelta, timezone
import unittest

from twitch_auto_clipper.performance import PerformanceModel, performance

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


def short(video, streamer, views, retention=None, days=3, **extra):
    return {"video_id": video, "channel": "gaming", "streamer": streamer, "views_1d": views,
            "retention_pct": retention, "seconds": 30, "source": "transcript",
            "uploaded_at": (NOW - timedelta(days=days)).isoformat(), **extra}


class PerformanceTests(unittest.TestCase):
    def test_views_retention_and_engagement_make_the_score(self):
        scores = performance([
            short("a", "x", 1200, 90, likes=40, comments=5),
            short("noise", "x", 20, 100, likes=5),  # 20 views: its share watched and likes are not counted
            short("b", "x", 1200, 40),
            short("c", "x", 10, 30),
        ])
        self.assertGreater(scores["a"], scores["b"])  # same views, watched to the end and liked
        self.assertGreater(scores["b"], scores["c"])
        self.assertLess(scores["noise"], scores["b"])

    def test_points_follow_real_results_stay_small_and_ignore_too_recent_shorts(self):
        history = [short(f"h{i}", "hit", 2000, 90) for i in range(8)]
        history += [short(f"f{i}", "flop", 5, 30) for i in range(8)]
        history += [short(f"l{i}", "listed", 5, 30) for i in range(8)]
        history += [short("new", "fresh", 0, 0, days=0)]  # published today: says nothing yet
        model = PerformanceModel(history, "gaming", NOW, protected=frozenset({"listed"}))
        hit, flop = model.points({"streamer": "hit", "seconds": 30}), model.points({"streamer": "flop", "seconds": 30})
        self.assertTrue(0 < hit <= 3 and -3 <= flop < 0)
        self.assertAlmostEqual(model.points({"streamer": "listed", "seconds": 30}), 0.0)  # a listed streamer never loses points
        self.assertNotIn("new", model.performance)
        few = PerformanceModel(history[:1] + history[8:9] + history[-1:], "gaming", NOW)
        self.assertLess(few.points({"streamer": "hit", "seconds": 30}), hit)  # one Short: much less sure

    def test_the_learned_points_weigh_less_when_their_predictions_were_wrong(self):
        good = [short(f"g{i}", "s", 10 * (i + 1), predicted_points=i) for i in range(25)]
        wrong = [short(f"w{i}", "s", 10 * (i + 1), predicted_points=-i) for i in range(25)]
        self.assertGreater(PerformanceModel(good, "gaming", NOW).reliability, 1.0)
        self.assertEqual(PerformanceModel(wrong, "gaming", NOW).reliability, 0.0)


if __name__ == "__main__":
    unittest.main()
