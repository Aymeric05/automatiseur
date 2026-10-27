from pathlib import Path
import tempfile
import unittest

from twitch_auto_clipper.speakers import parse_media
from twitch_auto_clipper.vod_shorts import VODShortsGenerator


class MediaSpeechTests(unittest.TestCase):
    def test_sentences_marked_as_media_become_spans_and_bad_numbers_are_ignored(self):
        numbered = [[{"start": 10.0, "end": 12.0}, {"start": 12.5, "end": 15.0}], [{"start": 50.0, "end": 52.0}]]
        text = '{"moments":[{"id":"m1","media":[2,7]},{"id":"m2","media":[]}]}'
        self.assertEqual(parse_media(text, numbered), [[[12.5, 15.0]], []])
        self.assertEqual(parse_media("not json", numbered), [[], []])

    def test_words_of_a_watched_video_are_left_out_of_the_subtitles(self):
        segments = [{"words": [
            {"word": "look", "start": 0.0, "end": 0.4},
            {"word": "subscribe", "start": 1.0, "end": 1.5},  # the video he watches
            {"word": "crazy", "start": 2.0, "end": 2.4},
        ]}]
        with tempfile.TemporaryDirectory() as directory:
            path, _ = VODShortsGenerator._write_subtitles(segments, Path(directory) / "s.mp4", 0.0, 3.0, [[0.9, 1.6]])
            content = path.read_text(encoding="utf-8-sig")
        self.assertIn("look", content)
        self.assertIn("crazy", content)
        self.assertNotIn("subscribe", content)


if __name__ == "__main__":
    unittest.main()
