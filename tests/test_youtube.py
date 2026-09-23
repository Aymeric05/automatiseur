from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from twitch_auto_clipper.youtube import (
    YouTubeUploadError,
    confirm_privacy_policy,
    confirm_upload_rights,
    upload_video,
)


class FakeMediaFileUpload:
    instances = []

    def __init__(self, path: str, mimetype: str, resumable: bool) -> None:
        self.path = path
        self.mimetype = mimetype
        self.resumable = resumable
        self.__class__.instances.append(self)


class FakeUploadRequest:
    def __init__(self) -> None:
        self.calls = 0

    def next_chunk(self):
        self.calls += 1
        return None, {"id": "youtube123"}


class FakeVideos:
    def __init__(self) -> None:
        self.arguments = None
        self.request = FakeUploadRequest()

    def insert(self, **kwargs):
        self.arguments = kwargs
        return self.request


class FakeChannels:
    def __init__(self, channel_id: str) -> None:
        self.channel_id = channel_id

    def list(self, **kwargs):
        return self

    def execute(self):
        return {"items": [{"id": self.channel_id, "snippet": {"title": "LiveActions!"}}]}


class FakeYouTubeService:
    def __init__(self, channel_id: str = "channel123") -> None:
        self.videos_api = FakeVideos()
        self.channels_api = FakeChannels(channel_id)

    def videos(self):
        return self.videos_api

    def channels(self):
        return self.channels_api


class YouTubeTests(unittest.TestCase):
    @patch("twitch_auto_clipper.youtube._load_google_dependencies")
    def test_upload_video_uses_resumable_upload_and_returns_url(self, load_dependencies):
        fake_service = FakeYouTubeService()
        load_dependencies.return_value = (None, None, None, None, Exception, FakeMediaFileUpload)

        with tempfile.TemporaryDirectory() as temporary_directory:
            video_path = Path(temporary_directory) / "clip.mp4"
            video_path.write_bytes(b"video")
            video_id, video_url = upload_video(
                video_path,
                "Mon Short",
                "Description",
                "unlisted",
                youtube_service=fake_service,
                made_for_kids=False,
                expected_channel_id="channel123",
            )

        self.assertEqual(video_id, "youtube123")
        self.assertEqual(video_url, "https://www.youtube.com/watch?v=youtube123")
        self.assertTrue(FakeMediaFileUpload.instances[-1].resumable)
        self.assertEqual(fake_service.videos_api.arguments["part"], "snippet,status")
        self.assertEqual(
            fake_service.videos_api.arguments["body"]["status"]["privacyStatus"],
            "unlisted",
        )
        self.assertFalse(
            fake_service.videos_api.arguments["body"]["status"]["selfDeclaredMadeForKids"]
        )

    def test_upload_video_rejects_missing_video(self) -> None:
        with self.assertRaisesRegex(YouTubeUploadError, "introuvable"):
            upload_video(Path("missing.mp4"), "Title", "Description")

    def test_upload_video_rejects_invalid_privacy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            video_path = Path(temporary_directory) / "clip.mp4"
            video_path.write_bytes(b"video")
            with self.assertRaisesRegex(YouTubeUploadError, "visibilite"):
                upload_video(video_path, "Title", "Description", "invalid")

    @patch("twitch_auto_clipper.youtube._load_google_dependencies")
    def test_upload_video_rejects_wrong_expected_channel_before_insert(self, load_dependencies):
        fake_service = FakeYouTubeService(channel_id="other-channel")
        load_dependencies.return_value = (None, None, None, None, Exception, FakeMediaFileUpload)
        with tempfile.TemporaryDirectory() as temporary_directory:
            video_path = Path(temporary_directory) / "clip.mp4"
            video_path.write_bytes(b"video")
            with self.assertRaisesRegex(YouTubeUploadError, "ne correspond pas"):
                upload_video(
                    video_path,
                    "Title",
                    "Description",
                    youtube_service=fake_service,
                    expected_channel_id="expected-channel",
                )
        self.assertIsNone(fake_service.videos_api.arguments)

    def test_confirmations_accept_and_reject(self) -> None:
        self.assertTrue(confirm_upload_rights(input_func=lambda _: "oui", output_func=lambda _: None))
        self.assertFalse(confirm_upload_rights(input_func=lambda _: "non", output_func=lambda _: None))
        self.assertTrue(
            confirm_privacy_policy(
                "https://example.test/privacy.html",
                input_func=lambda _: "yes",
                output_func=lambda _: None,
            )
        )
        self.assertFalse(
            confirm_privacy_policy(
                "https://example.test/privacy.html",
                input_func=lambda _: "no",
                output_func=lambda _: None,
            )
        )

    def test_confirm_privacy_policy_requires_url(self) -> None:
        with self.assertRaisesRegex(YouTubeUploadError, "YOUTUBE_PRIVACY_POLICY_URL"):
            confirm_privacy_policy("")


if __name__ == "__main__":
    unittest.main()
