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
    def test_token_missing_a_needed_scope_triggers_new_consent(self) -> None:
        import json
        from google.oauth2.credentials import Credentials
        from twitch_auto_clipper.youtube import (
            YOUTUBE_READONLY_SCOPE, YOUTUBE_UPLOAD_SCOPE, authenticate_youtube,
        )

        class FakeFlow:
            scopes = None

            @classmethod
            def from_client_secrets_file(cls, path, scopes):
                cls.scopes = scopes
                return cls()

            def run_local_server(self, host, port):
                assert host == "127.0.0.1"
                return type("Granted", (), {"to_json": lambda self: "{}"})()

        dependencies = (None, Credentials, FakeFlow, lambda *a, **k: "service", Exception, None)
        with tempfile.TemporaryDirectory() as directory, \
                patch("twitch_auto_clipper.youtube._load_google_dependencies", return_value=dependencies):
            token, secrets = Path(directory) / "token.json", Path(directory) / "client.json"
            secrets.write_text("{}", encoding="utf-8")
            token.write_text(json.dumps({  # fake test token, valid until 2099
                "token": "t", "refresh_token": "r", "client_id": "c", "client_secret": "s",
                "scopes": [YOUTUBE_UPLOAD_SCOPE], "expiry": "2099-01-01T00:00:00Z",
            }), encoding="utf-8")
            self.assertEqual(authenticate_youtube(secrets, token), "service")
            self.assertIsNone(FakeFlow.scopes)  # upload-only token is enough without channel check
            self.assertEqual(authenticate_youtube(secrets, token, "channel123"), "service")
            self.assertEqual(FakeFlow.scopes, [YOUTUBE_UPLOAD_SCOPE, YOUTUBE_READONLY_SCOPE])

    def test_rejected_authorization_asks_for_a_new_sign_in_only_when_interactive(self) -> None:
        import json
        from google.auth.exceptions import RefreshError
        from google.oauth2.credentials import Credentials
        from twitch_auto_clipper.youtube import YOUTUBE_UPLOAD_SCOPE, authenticate_youtube

        signed_in = []

        class FakeFlow:
            @classmethod
            def from_client_secrets_file(cls, path, scopes):
                return cls()

            def run_local_server(self, host, port):
                assert host == "127.0.0.1"
                signed_in.append(port)
                return type("Granted", (), {"to_json": lambda self: "{}"})()

        def refused(self, request):
            raise RefreshError("invalid_grant: Bad Request")

        dependencies = (lambda: None, Credentials, FakeFlow, lambda *a, **k: "service", Exception, None)
        with tempfile.TemporaryDirectory() as directory, \
                patch("twitch_auto_clipper.youtube._load_google_dependencies", return_value=dependencies), \
                patch.object(Credentials, "refresh", refused):
            token, secrets = Path(directory) / "token.json", Path(directory) / "client.json"
            secrets.write_text("{}", encoding="utf-8")
            token.write_text(json.dumps({  # fake test token, already expired
                "token": "t", "refresh_token": "r", "client_id": "c", "client_secret": "s",
                "scopes": [YOUTUBE_UPLOAD_SCOPE], "expiry": "2020-01-01T00:00:00Z",
            }), encoding="utf-8")
            with self.assertRaisesRegex(YouTubeUploadError, "reconnecter"):
                authenticate_youtube(secrets, token, allow_browser=False)
            self.assertEqual(signed_in, [])
            self.assertEqual(authenticate_youtube(secrets, token), "service")
            self.assertEqual(signed_in, [0])  # Google sign-in page opened once

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

    def test_retention_rows_become_per_video_values_without_any_sign_in(self) -> None:
        from unittest.mock import Mock

        from twitch_auto_clipper.youtube import fetch_video_retention

        service = Mock()
        service.reports().query().execute.return_value = {"rows": [["yt1", 900, 21.04, 87.51]]}
        build = Mock(return_value=service)
        with patch("twitch_auto_clipper.youtube._credentials", return_value="credentials") as credentials,                 patch("twitch_auto_clipper.youtube._load_google_dependencies",
                      return_value=(None, None, None, build, None, None)):
            retention = fetch_video_retention(["yt1"], "2026-10-13")
        self.assertEqual(retention, {"yt1": {"engaged_views": 900, "avg_view_seconds": 21.0, "retention_pct": 87.5}})
        self.assertFalse(credentials.call_args.args[3])  # allow_browser: never waits for a sign-in
        build.assert_called_once_with("youtubeAnalytics", "v2", credentials="credentials")
        query = service.reports().query.call_args.kwargs
        self.assertEqual((query["filters"], query["dimensions"]), ("video==yt1", "video"))

    @patch("twitch_auto_clipper.youtube.authenticate_youtube")
    def test_statistics_report_rejected_and_region_blocked_videos(self, authenticate) -> None:
        from twitch_auto_clipper.youtube import fetch_video_statistics

        authenticate.return_value.videos().list().execute.return_value = {"items": [
            {"id": "a", "statistics": {"viewCount": "10"}, "status": {"uploadStatus": "rejected", "rejectionReason": "copyright"}},
            {"id": "b", "statistics": {"viewCount": "3"}, "status": {"uploadStatus": "processed"},
             "contentDetails": {"regionRestriction": {"blocked": ["US", "CA"]}}},
            {"id": "c", "statistics": {"viewCount": "7"}, "status": {"uploadStatus": "rejected", "rejectionReason": "duplicate"}},
        ]}
        statistics = fetch_video_statistics(["a", "b", "c"])
        self.assertEqual(
            [statistics[key].get("problem") for key in "abc"], ["rejete (copyright)", "bloque dans 2 pays", None]
        )

    def test_the_second_channel_must_not_be_the_first_one(self) -> None:
        from unittest.mock import Mock

        from twitch_auto_clipper.youtube import YouTubeUploadError, authorize_channel

        with tempfile.TemporaryDirectory() as directory:
            token, analytics = Path(directory, "irl.json"), Path(directory, "irl-analytics.json")

            def sign_in(secrets, path, scopes, allow_browser, missing):
                path.write_text("{}", encoding="utf-8")
                return "credentials"

            for channel_id, title in (("UCgaming", "LiveActions!"), ("UCirl", "LiveActions IRL")):
                service = Mock()
                service.channels().list().execute.return_value = {"items": [{"id": channel_id, "snippet": {"title": title}}]}
                with patch("twitch_auto_clipper.youtube._credentials", side_effect=sign_in),                         patch("twitch_auto_clipper.youtube._load_google_dependencies",
                              return_value=(None, None, None, Mock(return_value=service), None, None)):
                    if channel_id == "UCgaming":
                        with self.assertRaises(YouTubeUploadError):
                            authorize_channel(Path("c.json"), token, analytics, "UCgaming")
                        self.assertFalse(token.exists())  # the wrong channel's token is not kept
                    else:
                        self.assertEqual(authorize_channel(Path("c.json"), token, analytics, "UCgaming"),
                                         ("UCirl", "LiveActions IRL"))
                        self.assertTrue(analytics.exists())  # the same sign-in also reads its retention

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
