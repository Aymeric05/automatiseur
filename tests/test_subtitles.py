from pathlib import Path
import tempfile
import unittest

from twitch_auto_clipper.subtitles import generate_ass_subtitles


class SubtitleTests(unittest.TestCase):
    def test_generate_ass_groups_words_with_real_relative_timestamps(self) -> None:
        segments = [
            {
                "start": 10.0,
                "end": 14.0,
                "text": "Hello world this works",
                "words": [
                    {"word": "Hello", "start": 10.0, "end": 10.5},
                    {"word": "world", "start": 10.6, "end": 11.2},
                    {"word": "this", "start": 11.3, "end": 11.7},
                    {"word": "works", "start": 11.8, "end": 12.4},
                ],
            }
        ]

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "captions.ass"
            generate_ass_subtitles(
                segments,
                output_path,
                clip_start=10.0,
                clip_end=13.0,
                max_words=3,
            )
            content = output_path.read_text(encoding="utf-8-sig")

        self.assertIn("Dialogue: 0,0:00:00.00,0:00:01.70,Default", content)
        self.assertIn("Hello world this", content)
        self.assertIn("Dialogue: 0,0:00:01.80,0:00:02.40,Default", content)
        self.assertIn("works", content)

    def test_generate_ass_ignores_words_outside_clip(self) -> None:
        segments = [
            {
                "start": 0.0,
                "end": 10.0,
                "words": [
                    {"word": "before", "start": 0.0, "end": 1.0},
                    {"word": "inside", "start": 2.0, "end": 3.0},
                    {"word": "after", "start": 8.0, "end": 9.0},
                ],
            }
        ]

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "captions.ass"
            generate_ass_subtitles(segments, output_path, clip_start=2.0, clip_end=4.0)
            content = output_path.read_text(encoding="utf-8-sig")

        self.assertIn("inside", content)
        self.assertNotIn("before", content)
        self.assertNotIn("after", content)


if __name__ == "__main__":
    unittest.main()
