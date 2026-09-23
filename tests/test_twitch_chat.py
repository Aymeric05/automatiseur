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


if __name__ == "__main__":
    unittest.main()
