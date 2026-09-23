from pathlib import Path
import unittest
from unittest.mock import patch

from twitch_auto_clipper.framing import build_vertical_filter, _sample_indices


class FramingTests(unittest.TestCase):
    def test_build_vertical_filter_falls_back_to_center(self) -> None:
        with patch("twitch_auto_clipper.framing.detect_horizontal_focus", return_value=None):
            video_filter = build_vertical_filter(Path("video.mp4"))

        self.assertEqual(
            video_filter,
            "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
        )

    def test_build_vertical_filter_uses_detected_horizontal_focus(self) -> None:
        with patch(
            "twitch_auto_clipper.framing.detect_horizontal_focus", return_value=0.25
        ):
            video_filter = build_vertical_filter(Path("video.mp4"))

        self.assertEqual(
            video_filter,
            "crop=ih*(9/16):ih:(iw-ih*(9/16))*0.2500:0,scale=1080:1920",
        )

    def test_sample_indices_cover_video_without_exceeding_last_frame(self) -> None:
        self.assertEqual(_sample_indices(100, 3), [0, 50, 99])
        self.assertEqual(_sample_indices(100, 1), [50])


if __name__ == "__main__":
    unittest.main()
