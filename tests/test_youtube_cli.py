from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from twitch_auto_clipper.cli import main


class YouTubeCliTests(unittest.TestCase):
    @patch.dict("os.environ", {"YOUTUBE_PRIVACY_POLICY_URL": "https://example.test/privacy.html"})
    @patch("twitch_auto_clipper.cli.confirm_privacy_policy", return_value=True)
    @patch("twitch_auto_clipper.cli.confirm_upload_rights", return_value=True)
    @patch("twitch_auto_clipper.cli.upload_video", return_value=("abc123", "https://www.youtube.com/watch?v=abc123"))
    def test_upload_youtube_cli_returns_video_id_and_url(self, upload_video, confirm_rights, confirm_privacy):
        with tempfile.TemporaryDirectory() as temporary_directory:
            video_path = Path(temporary_directory) / "clip.mp4"
            video_path.write_bytes(b"video")
            arguments = [
                "twitch_auto_clipper",
                "--upload-youtube",
                "--video",
                str(video_path),
                "--title",
                "Short test",
                "--description",
                "Description",
                "--privacy",
                "unlisted",
                "--not-made-for-kids",
            ]
            with patch.object(sys, "argv", arguments):
                result = main()

        self.assertEqual(result, 0)
        upload_video.assert_called_once()
        self.assertEqual(upload_video.call_args.args[3], "unlisted")
        self.assertFalse(upload_video.call_args.kwargs["made_for_kids"])

    @patch("twitch_auto_clipper.cli.upload_video")
    def test_upload_youtube_cli_requires_made_for_kids_declaration(self, upload_video):
        with tempfile.TemporaryDirectory() as temporary_directory:
            video_path = Path(temporary_directory) / "clip.mp4"
            video_path.write_bytes(b"video")
            arguments = [
                "twitch_auto_clipper", "--upload-youtube", "--video", str(video_path),
                "--title", "Short test",
            ]
            with patch.object(sys, "argv", arguments):
                with self.assertRaises(SystemExit):
                    main()
        upload_video.assert_not_called()


if __name__ == "__main__":
    unittest.main()
