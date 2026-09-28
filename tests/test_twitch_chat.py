from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from twitch_auto_clipper.twitch_chat import download_twitch_chat, get_twitch_vod_id


class TwitchChatTests(unittest.TestCase):
    def test_get_twitch_vod_id_extracts_id(self) -> None:
        self.assertEqual(
            get_twitch_vod_id("https://www.twitch.tv/videos/123456"),
            "123456",
        )

    @patch("twitch_auto_clipper.twitch_chat.subprocess.run")
    def test_download_twitch_chat_writes_json_path(self, run) -> None:
        def create_output(command, **kwargs):
            Path(command[-1]).write_text('{"comments": []}', encoding="utf-8")

        run.side_effect = create_output
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = download_twitch_chat(
                "https://www.twitch.tv/videos/123456",
                Path(temporary_directory) / "chat.json",
            )

        self.assertTrue(output_path.is_absolute())
        self.assertEqual(run.call_args.args[0][1], "chatdownload")
        self.assertEqual(run.call_args.args[0][3], "123456")


    @patch("twitch_auto_clipper.twitch_chat.subprocess.run")
    def test_chat_can_be_trimmed_with_millisecond_bounds(self, run) -> None:
        run.side_effect = lambda command, **kwargs: Path(command[-1]).write_text("{}", encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "c.json"
            download_twitch_chat("https://www.twitch.tv/videos/123456", output,
                                 start_seconds=60.5, end_seconds=600)
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("-b") + 1], "60500ms")
        self.assertEqual(command[command.index("-e") + 1], "600000ms")
        self.assertEqual(command[-2:], ["-o", str(output)])

    @patch("twitch_auto_clipper.twitch_chat.subprocess.run")
    def test_full_download_has_no_trim_and_zero_start_is_omitted(self, run) -> None:
        run.side_effect = lambda command, **kwargs: Path(command[-1]).write_text("{}", encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            download_twitch_chat("https://www.twitch.tv/videos/123456", Path(directory) / "a.json")
            full = run.call_args.args[0]
            download_twitch_chat("https://www.twitch.tv/videos/123456", Path(directory) / "b.json",
                                 start_seconds=0, end_seconds=600)
            trimmed = run.call_args.args[0]
        self.assertNotIn("-b", full)
        self.assertNotIn("-e", full)
        self.assertNotIn("-b", trimmed)
        self.assertIn("-e", trimmed)

    def test_invalid_chat_bounds_are_rejected_before_running(self) -> None:
        with patch("twitch_auto_clipper.twitch_chat.subprocess.run") as run:
            for start, end in ((-1, 10), (10, 10), (20, 5), (None, 0)):
                with self.assertRaises(ValueError):
                    download_twitch_chat("https://www.twitch.tv/videos/1", Path("x.json"), start, end)
        run.assert_not_called()

    def test_local_tools_copy_is_preferred_over_path(self) -> None:
        from twitch_auto_clipper import twitch_chat

        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory) / "TwitchDownloaderCLI.exe"
            local.write_bytes(b"exe")
            with patch.object(twitch_chat, "LOCAL_CLI", local), \
                    patch("twitch_auto_clipper.twitch_chat.shutil.which", return_value="C:/path/cli.exe"):
                self.assertEqual(twitch_chat.find_twitch_downloader_cli(), str(local))
            with patch.object(twitch_chat, "LOCAL_CLI", Path(directory) / "missing.exe"), \
                    patch("twitch_auto_clipper.twitch_chat.shutil.which", return_value="C:/path/cli.exe"):
                self.assertEqual(twitch_chat.find_twitch_downloader_cli(), "C:/path/cli.exe")


if __name__ == "__main__":
    unittest.main()
