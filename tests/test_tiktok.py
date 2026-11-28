import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from twitch_auto_clipper import tiktok


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class UploadDraftTests(unittest.TestCase):
    def test_a_big_video_goes_in_pieces_the_last_one_taking_the_rest(self):
        sent = []

        def urlopen(request, timeout=0):
            sent.append(request)
            if request.full_url == tiktok.INBOX_INIT_URL:
                return FakeResponse(json.dumps({"data": {"publish_id": "p1", "upload_url": "https://up"},
                                                "error": {"code": "ok"}}).encode())
            return FakeResponse(b"")

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(tiktok, "SINGLE_CHUNK_LIMIT", 20), patch.object(tiktok, "CHUNK_SIZE", 10), \
                patch("urllib.request.urlopen", side_effect=urlopen):
            video = Path(directory) / "short.mp4"
            video.write_bytes(b"x" * 25)
            self.assertEqual(tiktok.upload_draft(video, "token"), "p1")
        init = json.loads(sent[0].data)["source_info"]
        self.assertEqual((init["video_size"], init["chunk_size"], init["total_chunk_count"]), (25, 10, 2))
        self.assertEqual([r.get_header("Content-range") for r in sent[1:]], ["bytes 0-9/25", "bytes 10-24/25"])

    def test_a_missing_authorization_says_how_to_give_it(self):
        with self.assertRaisesRegex(tiktok.TikTokError, "--authorize-tiktok"):
            tiktok.access_token("key", "secret", Path("missing-tiktok-token.json"))


if __name__ == "__main__":
    unittest.main()


def _publish_with(options):
    sent = []

    def urlopen(request, timeout=0):
        sent.append(request)
        if request.full_url == tiktok.CREATOR_INFO_URL:
            return FakeResponse(json.dumps({"data": {"privacy_level_options": options}, "error": {"code": "ok"}}).encode())
        if request.full_url in (tiktok.INBOX_INIT_URL, tiktok.DIRECT_INIT_URL):
            return FakeResponse(json.dumps({"data": {"publish_id": "p1", "upload_url": "https://up"},
                                            "error": {"code": "ok"}}).encode())
        return FakeResponse(b"")

    with tempfile.TemporaryDirectory() as directory, patch("urllib.request.urlopen", side_effect=urlopen):
        video = Path(directory) / "short.mp4"
        video.write_bytes(b"x" * 25)
        return tiktok.publish(video, "token", "Speed Gets Shocked 😂 #twitch"), sent


def test_a_short_is_published_publicly_once_tiktok_allows_it():
    (how, _), sent = _publish_with(["PUBLIC_TO_EVERYONE", "FOLLOWER_OF_CREATOR", "SELF_ONLY"])
    assert how == "public"
    body = json.loads(sent[1].data)
    assert sent[1].full_url == tiktok.DIRECT_INIT_URL
    assert body["post_info"]["privacy_level"] == "PUBLIC_TO_EVERYONE"
    assert body["post_info"]["title"] == "Speed Gets Shocked 😂 #twitch"


def test_before_tiktok_audits_the_app_a_short_goes_to_the_drafts_never_private():
    (how, _), sent = _publish_with(["SELF_ONLY"])  # an unaudited app may only post privately
    assert how == "draft"
    assert sent[1].full_url == tiktok.INBOX_INIT_URL
    assert all(request.full_url != tiktok.DIRECT_INIT_URL for request in sent)
