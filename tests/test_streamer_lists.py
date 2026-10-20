from pathlib import Path
import tempfile
import unittest

from twitch_auto_clipper.streamer_lists import add_streamer, load_top_streamers


class StreamerListTests(unittest.TestCase):
    def test_a_streamer_is_added_once_with_a_note(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "blocked.txt"
            path.write_text("# header\nCaedrel  # manual", encoding="utf-8")  # no final newline
            self.assertFalse(add_streamer(path, "caedrel", "again"))
            self.assertTrue(add_streamer(path, "XQC", "auto 2026-10-18: Short x removed"))
            self.assertEqual(load_top_streamers(path), frozenset({"caedrel", "xqc"}))
            self.assertTrue(path.read_text(encoding="utf-8").endswith("xqc  # auto 2026-10-18: Short x removed\n"))
            self.assertTrue(add_streamer(Path(directory) / "new.txt", "kai", "first"))


if __name__ == "__main__":
    unittest.main()
