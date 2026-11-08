from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from twitch_auto_clipper.twitch import (
    TwitchDownloadError,
    download_twitch_vod,
    is_twitch_vod_url,
    resolve_twitch_video_url,
)


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

    def test_audio_only_download_keeps_only_the_audio_track(self) -> None:
        seen = {}

        class RecordingYoutubeDL(FakeYoutubeDL):
            def __init__(self, options):
                super().__init__(options)
                seen.update(options)

        with tempfile.TemporaryDirectory() as temporary_directory, patch(
            "twitch_auto_clipper.twitch._get_youtube_dl", return_value=RecordingYoutubeDL
        ):
            path = download_twitch_vod(
                "https://www.twitch.tv/videos/123456", Path(temporary_directory),
                max_seconds=600, audio_only=True, quiet=True,
            )
            self.assertEqual(path.name, "123456_audio.mp4")
            self.assertTrue(path.is_file())
        self.assertEqual(seen["format"], "bestaudio/worst")
        self.assertNotIn("merge_output_format", seen)
        self.assertTrue(seen["quiet"])
        self.assertIn("download_ranges", seen)

    def test_video_url_is_resolved_without_downloading(self) -> None:
        calls = []

        class ResolvingYoutubeDL(FakeYoutubeDL):
            def extract_info(self, url, download):
                calls.append((self.options["format"], download))
                return {"url": "https://example.test/1080p60/index.m3u8"}

        with patch("twitch_auto_clipper.twitch._get_youtube_dl", return_value=ResolvingYoutubeDL):
            url = resolve_twitch_video_url("https://www.twitch.tv/videos/123456")
        self.assertEqual(url, "https://example.test/1080p60/index.m3u8")
        self.assertEqual(calls, [("best", False)])

    def test_unresolvable_video_url_is_a_download_error(self) -> None:
        class Failing(FakeYoutubeDL):
            def extract_info(self, url, download):
                raise RuntimeError("subscriber-only VOD")

        with patch("twitch_auto_clipper.twitch._get_youtube_dl", return_value=Failing):
            with self.assertRaisesRegex(TwitchDownloadError, "subscriber-only"):
                resolve_twitch_video_url("https://www.twitch.tv/videos/123456")


if __name__ == "__main__":
    unittest.main()


class LongVodTests(unittest.TestCase):
    def test_a_long_vod_is_cut_to_its_last_hours_and_its_start_is_kept(self) -> None:
        import shutil
        import subprocess

        if not shutil.which("ffmpeg"):
            self.skipTest("FFmpeg missing")
        from twitch_auto_clipper.twitch import audio_offset

        class AudioYoutubeDL(FakeYoutubeDL):
            def extract_info(self, url, download):  # a 30 s "VOD": a tone whose pitch rises each second
                path = Path(self.options["outtmpl"].replace("%(ext)s", "mp4"))
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=30", "-c:a", "aac", str(path)], check=True)
                return {"id": "123", "ext": "mp4", "duration": 30}

        with tempfile.TemporaryDirectory() as directory, \
                patch("twitch_auto_clipper.twitch._get_youtube_dl", return_value=AudioYoutubeDL):
            path = download_twitch_vod("https://www.twitch.tv/videos/123", Path(directory), audio_only=True, last_seconds=10)
            seconds = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                                           capture_output=True, text=True).stdout)
            self.assertAlmostEqual(seconds, 10, delta=0.5)
            self.assertAlmostEqual(audio_offset(path), 20, delta=0.01)
            short = download_twitch_vod("https://www.twitch.tv/videos/124", Path(directory), audio_only=True, last_seconds=60)
            self.assertEqual(audio_offset(short), 0.0)  # shorter than the limit: kept whole
