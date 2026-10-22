from pathlib import Path
import unittest
from unittest.mock import patch

from twitch_auto_clipper.vod_pipeline import reaction_peak
from twitch_auto_clipper.vod_shorts import VODShortsGenerator, _build_short_ffmpeg_command


class ReactionPeakTests(unittest.TestCase):
    def test_the_emotion_heard_else_the_loudest_second_else_nothing(self):
        audio = Path("audio.mp4")
        self.assertEqual(reaction_peak({"onset": 112.0}, audio, 100.0, 130.0), 112.0)
        levels = [-40.0] * 30
        levels[9] = -20.0  # a scream 9 s in
        levels[1] = -10.0  # louder, but in the first seconds: seen right away anyway
        with patch("twitch_auto_clipper.vod_pipeline.audio_levels", return_value=levels):
            self.assertEqual(reaction_peak({}, audio, 100.0, 130.0), 109.0)
        with patch("twitch_auto_clipper.vod_pipeline.audio_levels", return_value=[-40.0] * 30):
            self.assertIsNone(reaction_peak({}, audio, 100.0, 130.0))  # nothing stands out
        with patch("twitch_auto_clipper.vod_pipeline.audio_levels", side_effect=OSError):
            self.assertIsNone(reaction_peak({}, audio, 100.0, 130.0))


class ColdOpenTests(unittest.TestCase):
    def test_the_teaser_starts_just_before_the_peak_and_stays_within_the_short(self):
        cold_open = VODShortsGenerator._cold_open
        self.assertEqual(cold_open({"peak": 109.0}, 100.0, 130.0), (108.0, 111.0))  # 3 s: the reaction is seen
        self.assertEqual(cold_open({"peak": 129.8}, 100.0, 130.0), (127.0, 130.0))
        self.assertIsNone(cold_open({"peak": 102.0}, 100.0, 130.0))  # seen in the first seconds
        self.assertIsNone(cold_open({}, 100.0, 130.0))

    def test_the_command_joins_the_teaser_then_the_short_with_subtitles_only_on_the_short(self):
        command = _build_short_ffmpeg_command(
            "https://vod.example/index.m3u8", Path("out.mp4"), 100.0, 130.0, "scale=-2:1920",
            Path("subs.ass"), Path("hook.png"), mute=[(3.0, 3.5)], teaser=(108.5, 110.0), teaser_mute=[(0.2, 0.4)],
        )
        self.assertEqual(command.count("-readrate"), 2)  # both readings at playback speed
        self.assertEqual([command[i + 1] for i, arg in enumerate(command) if arg == "-ss"], ["108.5", "100.0"])
        graph = command[command.index("-filter_complex") + 1]
        self.assertIn("[0:v]scale=-2:1920[tv]", graph)  # no subtitles on the teaser
        self.assertIn("[1:v]scale=-2:1920,subtitles=", graph)
        self.assertIn("between(t,0.2,0.4)", graph)
        self.assertIn("concat=n=2:v=1:a=1", graph)
        self.assertIn("[2:v]overlay", graph)  # the hook over both
        self.assertEqual(command[command.index("-preset") + 1], "veryfast")  # half the CPU of the default


if __name__ == "__main__":
    unittest.main()
