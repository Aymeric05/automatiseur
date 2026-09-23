from pathlib import Path
import unittest

from twitch_auto_clipper.video import build_ffmpeg_command, validate_clip_times


class VideoTests(unittest.TestCase):
    def test_build_ffmpeg_command_uses_clip_duration_and_vertical_format(self) -> None:
        command = build_ffmpeg_command(Path("input.mp4"), Path("output.mp4"), 10, 25)

        self.assertEqual(command[0], "ffmpeg")
        self.assertIn("-ss", command)
        self.assertEqual(command[command.index("-ss") + 1], "10")
        self.assertEqual(command[command.index("-t") + 1], "15")
        self.assertIn("crop=1080:1920", command[command.index("-vf") + 1])

    def test_build_ffmpeg_command_adds_subtitles_only_when_requested(self) -> None:
        command = build_ffmpeg_command(
            Path("input.mp4"),
            Path("output.mp4"),
            10,
            25,
            subtitles_path=Path("captions.ass"),
        )

        video_filter = command[command.index("-vf") + 1]
        self.assertIn("subtitles=", video_filter)

    def test_validate_clip_times_rejects_invalid_interval(self) -> None:
        with self.assertRaises(ValueError):
            validate_clip_times(20, 20)


if __name__ == "__main__":
    unittest.main()