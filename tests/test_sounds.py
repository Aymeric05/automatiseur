import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from twitch_auto_clipper import sounds


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg missing")
class SoundMixTests(unittest.TestCase):
    def test_music_and_effect_are_mixed_under_the_voice_and_the_picture_is_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            run = lambda *args: subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)
            run("-f", "lavfi", "-i", "color=c=gray:s=108x192:d=3", "-f", "lavfi", "-i", "sine=f=300:d=3",
                "-shortest", "-c:v", "libx264", "-c:a", "aac", str(tmp / "short.mp4"))
            run("-f", "lavfi", "-i", "sine=f=500:d=1", str(tmp / "music.mp3"))  # shorter: looped
            run("-f", "lavfi", "-i", "anoisesrc=d=0.3", str(tmp / "boom.mp3"))
            self.assertTrue(sounds.add_sounds(tmp / "short.mp4", tmp / "music.mp3", tmp / "boom.mp3", 1.5))
            probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
                                    "-of", "json", str(tmp / "short.mp4")], capture_output=True, text=True).stdout
            info = json.loads(probe)
            self.assertAlmostEqual(float(info["format"]["duration"]), 3.0, delta=0.2)
            self.assertEqual(sorted(s["codec_type"] for s in info["streams"]), ["audio", "video"])

    def test_nothing_to_add_leaves_the_short_unchanged(self):
        self.assertFalse(sounds.add_sounds(Path("missing.mp4"), None, None, None))


class LibraryTests(unittest.TestCase):
    def test_a_sound_is_picked_only_from_the_library_files_that_exist(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            (tmp / "music_hype").mkdir()
            (tmp / "music_hype" / "1.mp3").write_bytes(b"x")
            (tmp / "library.json").write_text(json.dumps({"library": {"music_hype": ["1.mp3", "2.mp3"]}}))
            self.assertEqual(sounds.pick(tmp, "music_hype"), tmp / "music_hype" / "1.mp3")
            self.assertIsNone(sounds.pick(tmp, "music_sad"))


if __name__ == "__main__":
    unittest.main()
