"""Twitch Helix API helpers for discovering live streams."""

from dataclasses import dataclass
import json
import os
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


TOKEN_URL = "https://id.twitch.tv/oauth2/token"
STREAMS_URL = "https://api.twitch.tv/helix/streams"
VIDEOS_URL = "https://api.twitch.tv/helix/videos"
MAX_PAGE_SIZE = 100


class TwitchAPIError(RuntimeError):
    """Raised when Twitch authentication or an API request fails."""


@dataclass(frozen=True)
class LiveStream:
    stream_id: str
    broadcaster_id: str
    broadcaster_login: str
    broadcaster_name: str
    viewer_count: int
    title: str
    game_name: str
    language: str
    started_at: str


@dataclass(frozen=True)
class TwitchVOD:
    vod_id: str
    stream_id: str
    broadcaster_id: str
    title: str
    broadcaster_login: str = ""
    broadcaster_name: str = ""


class TwitchAPIClient:
    """Small client for app-authenticated Twitch live stream discovery."""

    def fetch_english_streams(
        self,
        limit: int | None = None,
        page_size: int = MAX_PAGE_SIZE,
        min_viewers: int | None = None,
    ) -> list[LiveStream]:
        """Fetch streams in Twitch's viewer-count order, following pagination.

        With ``min_viewers``, pagination stops after the first page whose
        streams are *all* below the threshold. Requiring a whole page (not a
        single stream) below it tolerates the small ordering shifts that
        happen while paginating, so eligible streams are not cut off early.
        """
        if limit is not None and limit < 1:
            raise ValueError("limit must be positive")
        if not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")

        access_token = self._get_app_access_token()
        streams: list[LiveStream] = []
        seen_stream_ids: set[str] = set()
        cursor: str | None = None
        seen_cursors: set[str] = set()

        while limit is None or len(streams) < limit:
            params = {"first": page_size, "language": "en"}
            if cursor:
                params["after"] = cursor
            payload = self._request_json(
                Request(
                    f"{STREAMS_URL}?{urlencode(params)}",
                    headers={
                        "Client-Id": self._client_id(),
                        "Authorization": f"Bearer {access_token}",
                    },
                )
            )

            # Ordering shifts while paginating, so a stream can appear on two
            # pages of the same snapshot: keep only its first occurrence.
            page = [self._parse_stream(item) for item in payload.get("data", [])]
            for stream in page:
                if stream.stream_id not in seen_stream_ids:
                    seen_stream_ids.add(stream.stream_id)
                    streams.append(stream)
            if limit is not None and len(streams) >= limit:
                return streams[:limit]
            if min_viewers is not None and page and all(
                stream.viewer_count < min_viewers for stream in page
            ):
                break

            next_cursor = payload.get("pagination", {}).get("cursor")
            if not next_cursor or next_cursor in seen_cursors:
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor

        return streams

    def fetch_live_streams_by_user_ids(self, user_ids: list[str]) -> dict[str, LiveStream]:
        """Return the current live stream of each broadcaster that is online.

        Broadcasters missing from the result are offline. Helix accepts at
        most 100 ``user_id`` values per request, so lookups are batched.
        """
        unique_ids = list(dict.fromkeys(user_ids))
        if not unique_ids:
            return {}
        access_token = self._get_app_access_token()
        live: dict[str, LiveStream] = {}
        for start in range(0, len(unique_ids), MAX_PAGE_SIZE):
            batch = unique_ids[start : start + MAX_PAGE_SIZE]
            query = urlencode([("user_id", user_id) for user_id in batch] + [("first", MAX_PAGE_SIZE)])
            payload = self._request_json(
                Request(
                    f"{STREAMS_URL}?{query}",
                    headers={
                        "Client-Id": self._client_id(),
                        "Authorization": f"Bearer {access_token}",
                    },
                )
            )
            for item in payload.get("data", []):
                stream = self._parse_stream(item)
                live[stream.broadcaster_id] = stream
        return live

    def fetch_vod(self, vod_id: str) -> TwitchVOD | None:
        """Return one archived VOD by its id, or None if it does not exist."""
        payload = self._request_json(
            Request(
                f"{VIDEOS_URL}?{urlencode({'id': vod_id})}",
                headers={
                    "Client-Id": self._client_id(),
                    "Authorization": f"Bearer {self._get_app_access_token()}",
                },
            )
        )
        for item in payload.get("data", []):
            return TwitchVOD(
                vod_id=item["id"],
                stream_id=item.get("stream_id") or "",
                broadcaster_id=item["user_id"],
                title=item.get("title", ""),
                broadcaster_login=item.get("user_login", ""),
                broadcaster_name=item.get("user_name", ""),
            )
        return None

    def find_vod_for_stream(
        self,
        broadcaster_id: str,
        stream_id: str,
    ) -> TwitchVOD | None:
        """Find the archived VOD whose Helix stream_id matches this live."""
        access_token = self._get_app_access_token()
        cursor: str | None = None
        seen_cursors: set[str] = set()

        while True:
            params = {
                "user_id": broadcaster_id,
                "type": "archive",
                "first": MAX_PAGE_SIZE,
                "sort": "time",
            }
            if cursor:
                params["after"] = cursor
            payload = self._request_json(
                Request(
                    f"{VIDEOS_URL}?{urlencode(params)}",
                    headers={
                        "Client-Id": self._client_id(),
                        "Authorization": f"Bearer {access_token}",
                    },
                )
            )

            for item in payload.get("data", []):
                if item.get("stream_id") == stream_id:
                    return TwitchVOD(
                        vod_id=item["id"],
                        stream_id=item["stream_id"],
                        broadcaster_id=item["user_id"],
                        title=item["title"],
                    )

            next_cursor = payload.get("pagination", {}).get("cursor")
            if not next_cursor or next_cursor in seen_cursors:
                return None
            seen_cursors.add(next_cursor)
            cursor = next_cursor

    @staticmethod
    def _client_id() -> str:
        client_id = os.environ.get("TWITCH_CLIENT_ID")
        if not client_id:
            raise TwitchAPIError("TWITCH_CLIENT_ID is not configured.")
        return client_id

    def _get_app_access_token(self) -> str:
        client_id = self._client_id()
        client_secret = os.environ.get("TWITCH_CLIENT_SECRET")
        if not client_secret:
            raise TwitchAPIError("TWITCH_CLIENT_SECRET is not configured.")

        body = urlencode(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
            }
        ).encode("utf-8")
        payload = self._request_json(
            Request(
                TOKEN_URL,
                data=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
        )
        access_token = payload.get("access_token")
        if not access_token:
            raise TwitchAPIError("Twitch token response did not include an access token.")
        return access_token

    @staticmethod
    def _request_json(request: Request) -> dict:
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except (URLError, OSError, json.JSONDecodeError) as error:
            raise TwitchAPIError(f"Twitch API request failed: {error}") from error

    @staticmethod
    def _parse_stream(item: dict) -> LiveStream:
        return LiveStream(
            stream_id=item["id"],
            broadcaster_id=item["user_id"],
            broadcaster_login=item["user_login"],
            broadcaster_name=item["user_name"],
            viewer_count=item["viewer_count"],
            title=item["title"],
            game_name=item["game_name"],
            language=item["language"],
            started_at=item["started_at"],
        )