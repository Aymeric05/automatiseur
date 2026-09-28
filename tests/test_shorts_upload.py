"""Tests for private YouTube publication and post-upload cleanup."""

from pathlib import Path
import json
import tempfile
import unittest

from twitch_auto_clipper.shorts_metadata import ShortMetadata
from twitch_auto_clipper.shorts_upload import VODShortsUploader, format_short_upload_result
from twitch_auto_clipper.vod_shorts import VODShortResult
from twitch_auto_clipper.youtube import YouTubeUploadError

METADATA = ShortMetadata(title="Streamer: “no way”", description="“no way”")


class ShortsUploadTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.source = self.tmp / "vod_1.mp4"
        self.source.write_bytes(b"source")
        self.transcript = self.tmp / "vod_1_transcript.json"
        self.transcript.write_text("[]", encoding="utf-8")
        self.manifest = self.tmp / "vod_1_processing.json"
        self.manifest.write_text(json.dumps({"vod_id": "vod_1"}), encoding="utf-8")
        self.short_path = self.tmp / "vod_1_candidate_1_short.mp4"
        self.short_path.write_bytes(b"short")

    def tearDown(self):
        self._tmp.cleanup()

    def _short(self, status="generated"):
        return VODShortResult(
            vod_id="vod_1", candidate_id="candidate_1", source_path=self.source,
            output_path=self.short_path, start=15.0, end=35.0, clip_budget=2,
            gemini_score=88.0, gemini_justification="why", status=status,
        )

    def _manifest(self):
        return json.loads(self.manifest.read_text(encoding="utf-8"))

    def _assert_protected_files_kept(self):
        self.assertTrue(self.source.is_file())
        self.assertTrue(self.transcript.is_file())
        self.assertTrue(self.manifest.is_file())

    def test_confirmed_upload_is_private_recorded_and_deletes_local_short(self):
        calls = []

        def uploader(path, title, description, privacy, secrets, token, **kwargs):
            calls.append((path, title, privacy, kwargs))
            return "yt123", "https://www.youtube.com/watch?v=yt123"

        result = VODShortsUploader(self.tmp, uploader=uploader).upload("vod_1", self._short(), METADATA)

        self.assertEqual(result.status, "uploaded")
        self.assertTrue(result.local_file_deleted)
        self.assertFalse(self.short_path.exists())
        self.assertEqual(calls[0][2], "private")
        self.assertFalse(calls[0][3]["made_for_kids"])
        record = self._manifest()["youtube_uploads"]["candidate_1"]
        self.assertEqual(record["video_id"], "yt123")
        self.assertEqual(record["privacy"], "private")
        self.assertEqual(record["title"], METADATA.title)
        self._assert_protected_files_kept()

    def test_failed_upload_keeps_local_short(self):
        def uploader(*args, **kwargs):
            raise YouTubeUploadError("quota exceeded")

        result = VODShortsUploader(self.tmp, uploader=uploader).upload("vod_1", self._short(), METADATA)

        self.assertEqual(result.status, "error")
        self.assertTrue(self.short_path.is_file())
        self.assertNotIn("youtube_uploads", self._manifest())
        self.assertIn("quota", self._manifest()["youtube_upload_errors"]["candidate_1"])
        self._assert_protected_files_kept()

    def test_unexpected_exception_keeps_local_short(self):
        def uploader(*args, **kwargs):
            raise ConnectionResetError("network dropped")

        result = VODShortsUploader(self.tmp, uploader=uploader).upload("vod_1", self._short(), METADATA)

        self.assertEqual(result.status, "error")
        self.assertTrue(self.short_path.is_file())

    def test_interruption_propagates_and_keeps_local_short(self):
        def uploader(*args, **kwargs):
            raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            VODShortsUploader(self.tmp, uploader=uploader).upload("vod_1", self._short(), METADATA)
        self.assertTrue(self.short_path.is_file())
        self.assertNotIn("youtube_uploads", self._manifest())

    def test_unconfirmed_upload_without_video_id_keeps_local_short(self):
        result = VODShortsUploader(self.tmp, uploader=lambda *a, **k: ("", "")).upload(
            "vod_1", self._short(), METADATA
        )
        self.assertEqual(result.status, "error")
        self.assertTrue(self.short_path.is_file())

    def test_already_uploaded_short_is_not_uploaded_twice(self):
        self.manifest.write_text(json.dumps({"youtube_uploads": {
            "candidate_1": {"video_id": "old", "url": "https://youtu.be/old"}
        }}), encoding="utf-8")
        calls = []
        result = VODShortsUploader(self.tmp, uploader=lambda *a, **k: calls.append(a)).upload(
            "vod_1", self._short(), METADATA
        )
        self.assertEqual(result.status, "already_uploaded")
        self.assertEqual(result.video_id, "old")
        self.assertEqual(calls, [])

    def test_errored_short_is_skipped(self):
        calls = []
        result = VODShortsUploader(self.tmp, uploader=lambda *a, **k: calls.append(a)).upload(
            "vod_1", self._short(status="error"), METADATA
        )
        self.assertEqual(result.status, "skipped")
        self.assertEqual(calls, [])

    def test_cleanup_never_deletes_non_short_files(self):
        self.assertFalse(VODShortsUploader._delete_local(self.source))
        self.assertFalse(VODShortsUploader._delete_local(self.transcript))
        self._assert_protected_files_kept()

    def test_format_mentions_kept_file_on_failure(self):
        result = VODShortsUploader(
            self.tmp, uploader=lambda *a, **k: (_ for _ in ()).throw(YouTubeUploadError("x"))
        ).upload("vod_1", self._short(), METADATA)
        self.assertIn("fichier local conserve", format_short_upload_result(result))


if __name__ == "__main__":
    unittest.main()
