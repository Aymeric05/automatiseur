import json
import unittest

from twitch_auto_clipper.focus import parse_focus
from twitch_auto_clipper.vod_shorts import _build_vertical_filter_zoomed_out


class FocusTests(unittest.TestCase):
    def test_only_valid_screen_boxes_give_a_center(self):
        answer = json.dumps({"frames": [
            {"index": 1, "scene": "screen", "box_2d": [250, 0, 800, 547]},
            {"index": 2, "scene": "camera", "box_2d": [0, 0, 1000, 1000]},  # IRL: stays centered
            {"index": 3, "scene": "screen", "box_2d": [0, 600, 1000, 200]},  # xmax before xmin
            {"index": 9, "scene": "screen", "box_2d": [0, 0, 1000, 1000]},  # no such frame
        ]})
        self.assertEqual(parse_focus(answer, 3), [0.274, None, None])
        self.assertEqual(parse_focus("not json", 2), [None, None])

    def test_the_crop_window_follows_the_focus_within_the_frame(self):
        self.assertNotIn("iw-ow", _build_vertical_filter_zoomed_out())  # centered, as before
        self.assertIn("crop='min(iw,1220)':ih:'max(0,min(iw-ow,0.274*iw-ow/2))':0",
                      _build_vertical_filter_zoomed_out(None, 0.274))
        self.assertIn("1.000*iw", _build_vertical_filter_zoomed_out(None, 7))


if __name__ == "__main__":
    unittest.main()
