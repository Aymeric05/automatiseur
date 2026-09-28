from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from twitch_auto_clipper.twitch import download_twitch_vod, is_twitch_vod_url


class FakeYoutubeDL:
    def __init__(self, options: dict[str, object]) -> None:
        self.options = options

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def extract_info(self, url: str, download: bool) -> dict[str, str]:
        output_path = Path(self.options["outtmpl"].replace("%(id)s", "123").replace("%(ext)s", "mp4"))
        output_path.write_bytes(b"video")
        return {"id": "123", "ext": "mp4"}

    def prepare_filename(self, info: dict[str, str]) -> str:
        return str(Path(self.options["outtmpl"].replace("%(id)s", info["id"]).replace("%(ext)s", info["ext"])))


class TwitchTests(unittest.TestCase):
    def test_is_twitch_vod_url_accepts_standard_url(self) -> None:
        self.assertTrue(is_twitch_vod_url("https://www.twitch.tv/videos/123456"))

    def test_is_twitch_vod_url_rejects_non_vod_url(self) -> None:
        self.assertFalse(is_twitch_vod_url("https://www.twitch.tv/channel"))
        self.assertFalse(is_twitch_vod_url("https://example.com/videos/123456"))

    @patch("twitch_auto_clipper.twitch._get_youtube_dl", return_value=FakeYoutubeDL)
    def test_download_twitch_vod_returns_local_mp4(self, get_youtube_dl) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = download_twitch_vod(
                "https://www.twitch.tv/videos/123456",
                Path(temporary_directory),
            )

        # Named after the numeric VOD id, not yt-dlp's "v<id>".
        self.assertEqual(output_path.name, "123456.mp4")
        self.assertTrue(get_youtube_dl.called)

    def test_download_can_be_limited_in_duration_and_resolution(self) -> None:
        seen = {}

        class RecordingYoutubeDL(FakeYoutubeDL):
            def __init__(self, options):
                super().__init__(options)
                seen.update(options)

        with tempfile.TemporaryDirectory() as temporary_directory, patch(
            "twitch_auto_clipper.twitch._get_youtube_dl", return_value=RecordingYoutubeDL
        ):
            download_twitch_vod(
                "https://www.twitch.tv/videos/123456", Path(temporary_directory),
                max_seconds=600, max_height=720,
            )

        self.assertIn("height<=720", seen["format"])
        self.assertIn("download_ranges", seen)


if __name__ == "__main__":
    unittest.main()
