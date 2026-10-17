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
            written = download_twitch_chat("https://www.twitch.tv/videos/123456", output,
                                           start_seconds=60.5, end_seconds=600)
            command = run.call_args.args[0]
            # Written under a temporary name, renamed once complete.
            self.assertTrue(written.is_file() and not output.with_name("c.part.json").exists())
        self.assertEqual(command[command.index("-b") + 1], "60500ms")
        self.assertEqual(command[command.index("-e") + 1], "600000ms")
        self.assertEqual(command[-2:], ["-o", str(output.with_name("c.part.json"))])

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

    @patch("twitch_auto_clipper.twitch_chat.subprocess.run")
    def test_stalled_chat_download_times_out(self, run) -> None:
        import subprocess

        from twitch_auto_clipper.twitch_chat import TwitchChatDownloadError

        run.side_effect = subprocess.TimeoutExpired("TwitchDownloaderCLI", 3600)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(TwitchChatDownloadError, "interrompu"):
                download_twitch_chat("https://www.twitch.tv/videos/1", Path(directory) / "c.json")
        self.assertIn("timeout", run.call_args.kwargs)

    @patch("twitch_auto_clipper.twitch_chat.time.sleep")
    @patch("twitch_auto_clipper.twitch_chat.subprocess.run")
    def test_a_crash_of_the_downloader_is_retried_once_then_explained(self, run, sleep) -> None:
        import subprocess

        from twitch_auto_clipper.twitch_chat import TwitchChatDownloadError

        crash = subprocess.CalledProcessError(3762504530, "TwitchDownloaderCLI", stderr="Unhandled exception. HttpRequestException")

        calls = []

        def crash_then_work(command, **kwargs):
            calls.append(command)
            if len(calls) == 1:
                raise crash
            Path(command[-1]).write_text("{}", encoding="utf-8")

        run.side_effect = crash_then_work
        with tempfile.TemporaryDirectory() as directory:
            download_twitch_chat("https://www.twitch.tv/videos/1", Path(directory) / "c.json")
        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once()

        run.reset_mock()
        run.side_effect = [crash, crash]
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(TwitchChatDownloadError, "HttpRequestException"):
                download_twitch_chat("https://www.twitch.tv/videos/1", Path(directory) / "c.json")
        self.assertEqual(run.call_count, 2)

    @patch("twitch_auto_clipper.twitch_chat.subprocess.run")
    def test_leftover_partial_file_never_blocks_on_a_question(self, run) -> None:
        import subprocess

        run.side_effect = lambda command, **kwargs: Path(command[-1]).write_text("{}", encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "c.json"
            output.with_name("c.part.json").write_bytes(b"")  # left by an interrupted run
            download_twitch_chat("https://www.twitch.tv/videos/1", output)
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--collision") + 1], "Overwrite")
        self.assertIs(run.call_args.kwargs["stdin"], subprocess.DEVNULL)

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
