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
