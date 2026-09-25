import json
import os
import unittest
from unittest.mock import patch

from twitch_auto_clipper.twitch_api import (
    MAX_PAGE_SIZE,
    TOKEN_URL,
    TwitchAPIClient,
    TwitchAPIError,
    VIDEOS_URL,
)


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def stream_payload(stream_id: str, viewers: int) -> dict[str, object]:
    return {
        "id": stream_id,
        "user_id": f"broadcaster-{stream_id}",
        "user_login": f"login-{stream_id}",
        "user_name": f"Broadcaster {stream_id}",
        "viewer_count": viewers,
        "title": f"Title {stream_id}",
        "game_name": "Game",
        "language": "en",
        "started_at": "2026-09-25T12:00:00Z",
    }


class TwitchAPITests(unittest.TestCase):
    @patch.dict(
        os.environ,
        {"TWITCH_CLIENT_ID": "test-client-id", "TWITCH_CLIENT_SECRET": "test-secret"},
        clear=True,
    )
    @patch("twitch_auto_clipper.twitch_api.urlopen")
    def test_fetch_english_streams_authenticates_and_follows_cursor(self, urlopen) -> None:
        urlopen.side_effect = [
            FakeResponse({"access_token": "app-token"}),
            FakeResponse(
                {
                    "data": [stream_payload("one", 500), stream_payload("two", 400)],
                    "pagination": {"cursor": "next-page"},
                }
            ),
            FakeResponse(
                {"data": [stream_payload("three", 300)], "pagination": {}}
            ),
        ]

        streams = TwitchAPIClient().fetch_english_streams(limit=3)

        self.assertEqual([stream.stream_id for stream in streams], ["one", "two", "three"])
        self.assertEqual(streams[0].broadcaster_id, "broadcaster-one")
        self.assertEqual(streams[0].broadcaster_login, "login-one")
        self.assertEqual(streams[0].broadcaster_name, "Broadcaster one")
        self.assertEqual(streams[0].viewer_count, 500)
        self.assertEqual(streams[0].game_name, "Game")
        self.assertEqual(streams[0].language, "en")
        self.assertEqual(streams[0].started_at, "2026-09-25T12:00:00Z")

        token_request = urlopen.call_args_list[0].args[0]
        self.assertEqual(token_request.full_url, TOKEN_URL)
        self.assertEqual(token_request.get_method(), "POST")
        self.assertIn(b"grant_type=client_credentials", token_request.data)
        self.assertIn(b"client_secret=test-secret", token_request.data)

        first_page_request = urlopen.call_args_list[1].args[0]
        self.assertIn("first=100", first_page_request.full_url)
        self.assertIn("language=en", first_page_request.full_url)
        self.assertEqual(first_page_request.get_header("Client-id"), "test-client-id")
        self.assertEqual(first_page_request.get_header("Authorization"), "Bearer app-token")
        next_page_request = urlopen.call_args_list[2].args[0]
        self.assertIn("after=next-page", next_page_request.full_url)

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_credentials_raise_without_making_request(self) -> None:
        with patch("twitch_auto_clipper.twitch_api.urlopen") as urlopen:
            with self.assertRaisesRegex(TwitchAPIError, "TWITCH_CLIENT_ID"):
                TwitchAPIClient().fetch_english_streams()
        urlopen.assert_not_called()

    def test_page_size_cannot_exceed_twitch_limit(self) -> None:
        with self.assertRaises(ValueError):
            TwitchAPIClient().fetch_english_streams(page_size=MAX_PAGE_SIZE + 1)

    @patch.dict(
        os.environ,
        {"TWITCH_CLIENT_ID": "test-client-id", "TWITCH_CLIENT_SECRET": "test-secret"},
        clear=True,
    )
    @patch("twitch_auto_clipper.twitch_api.urlopen")
    def test_find_vod_matches_stream_id_and_follows_video_cursor(self, urlopen) -> None:
        urlopen.side_effect = [
            FakeResponse({"access_token": "app-token"}),
            FakeResponse(
                {
                    "data": [
                        {"id": "other-vod", "stream_id": "other", "user_id": "broadcaster", "title": "Other"}
                    ],
                    "pagination": {"cursor": "next"},
                }
            ),
            FakeResponse(
                {
                    "data": [
                        {"id": "vod-1", "stream_id": "stream-1", "user_id": "broadcaster", "title": "Archive"}
                    ],
                    "pagination": {},
                }
            ),
        ]

        vod = TwitchAPIClient().find_vod_for_stream("broadcaster", "stream-1")

        self.assertEqual(vod.vod_id, "vod-1")
        self.assertEqual(vod.stream_id, "stream-1")
        self.assertEqual(vod.broadcaster_id, "broadcaster")
        self.assertIn(VIDEOS_URL, urlopen.call_args_list[1].args[0].full_url)
        self.assertIn("user_id=broadcaster", urlopen.call_args_list[1].args[0].full_url)
        self.assertIn("type=archive", urlopen.call_args_list[1].args[0].full_url)
        self.assertIn("after=next", urlopen.call_args_list[2].args[0].full_url)


if __name__ == "__main__":
    unittest.main()