from pathlib import Path
import tempfile
import unittest

from twitch_auto_clipper.subtitles import BLURRED_WORD, generate_ass_subtitles


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


class SwearWordSubtitleTests(unittest.TestCase):
    def test_swear_words_are_blurred_not_spelled(self) -> None:
        segments = [{"words": [
            {"start": 0.0, "end": 0.3, "word": " what"},
            {"start": 0.3, "end": 0.6, "word": " the"},
            {"start": 0.6, "end": 0.9, "word": " fuck?"},
        ]}]
        with tempfile.TemporaryDirectory() as directory:
            path = generate_ass_subtitles(segments, Path(directory) / "s.ass")
            dialogue = path.read_text(encoding="utf-8-sig").splitlines()[-1]
        self.assertTrue(dialogue.endswith("what the " + BLURRED_WORD % "fuck?"))


class SubtitleJoinTests(unittest.TestCase):
    def test_punctuation_tokens_stick_to_the_previous_word(self) -> None:
        from twitch_auto_clipper.subtitles import _join_words

        self.assertEqual(_join_words(["4", "p", ".m.", "Oh"]), "4 p.m. Oh")
        self.assertEqual(_join_words(["cost", "$7", ",000."]), "cost $7,000.")
        self.assertEqual(_join_words(["it", "'s", "fine"]), "it's fine")


class HookImageTests(unittest.TestCase):
    def test_joined_emojis_keep_their_base_emoji_only(self) -> None:
        from twitch_auto_clipper.subtitles import _simple_emojis

        runner = "\U0001F3C3\u200d\u2642\ufe0f"  # man running
        thumb = "\U0001F44D\U0001F3FD"  # thumbs up, medium skin tone
        self.assertEqual(_simple_emojis(f"Run {runner} now {thumb}"), "Run \U0001F3C3 now \U0001F44D")

    def test_hook_is_white_text_without_emojis_on_a_transparent_image(self) -> None:
        from twitch_auto_clipper.subtitles import HOOK_MAX_TEXT_WIDTH, SubtitleGenerationError, render_hook_image

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hook.png"
            try:
                render_hook_image("He did NOT expect this ending at all 😱🔥 wait for it", path)
            except SubtitleGenerationError as error:
                self.skipTest(str(error))  # Windows fonts missing
            from PIL import Image

            with Image.open(path) as image:
                self.assertLessEqual(image.width, HOOK_MAX_TEXT_WIDTH + 100)
                self.assertGreater(image.height, 200)  # wrapped on two lines
                self.assertEqual(image.getpixel((0, 0))[3], 0)  # no box: transparent around the text
                colors = image.getcolors(1_000_000)
            self.assertFalse(any(r > 200 and g < 160 and b < 100 and a == 255 for _, (r, g, b, a) in colors))  # no flame emoji
            self.assertTrue(any(min(r, g, b) > 240 and a == 255 for _, (r, g, b, a) in colors))  # white text


if __name__ == "__main__":
    unittest.main()
