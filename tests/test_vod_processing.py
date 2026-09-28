import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from twitch_auto_clipper.twitch_chat import TwitchChatDownloadError
from twitch_auto_clipper.vod_acquisition import VODAcquisitionResult
from twitch_auto_clipper.vod_processing import VODProcessingPipeline


def acquired_vod(video_path: Path) -> VODAcquisitionResult:
    return VODAcquisitionResult(
        stream_id="stream-1",
        clip_budget=10,
        status="downloaded",
        broadcaster_id="broadcaster-1",
        broadcaster_login="login-1",
        broadcaster_name="Broadcaster One",
        vod_id="vod-1",
        downloaded_path=video_path,
    )


class VODProcessingTests(unittest.TestCase):
    def test_process_saves_word_timestamps_chat_timestamps_and_metadata_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            video_path = root / "vod-1.mp4"
            video_path.write_bytes(b"video")
            transcriber = Mock(
                return_value=[
                    {
                        "start": 1.0,
                        "end": 2.0,
                        "text": " hello",
                        "words": [{"word": " hello", "start": 1.0, "end": 1.5}],
                    }
                ]
            )

            def download_chat(url: str, output_path: Path) -> Path:
                output_path.write_text(
                    json.dumps(
                        {
                            "comments": [
                                {
                                    "content_offset_seconds": 1.25,
                                    "message": {"body": "hello chat"},
                                }
                            ]
                        }
                    ),
                    encoding="utf-8",
                )
                return output_path

            chat_downloader = Mock(side_effect=download_chat)
            pipeline = VODProcessingPipeline(
                output_dir=root / "output",
                transcriber=transcriber,
                chat_downloader=chat_downloader,
            )
            acquisition = acquired_vod(video_path)

            first = pipeline.process(acquisition)
            second = pipeline.process(acquisition)

            self.assertEqual(first.transcription_status, "completed")
            self.assertEqual(first.chat_status, "downloaded")
            self.assertEqual(second.transcription_status, "already_completed")
            self.assertEqual(second.chat_status, "already_completed")
            self.assertEqual(first.stream_id, "stream-1")
            self.assertEqual(first.vod_id, "vod-1")
            self.assertEqual(first.broadcaster_id, "broadcaster-1")
            self.assertEqual(first.broadcaster_login, "login-1")
            self.assertEqual(first.broadcaster_name, "Broadcaster One")
            self.assertEqual(first.clip_budget, 10)
            transcriber.assert_called_once_with(
                video_path,
                device="cpu",
                compute_type="int8",
            )
            chat_downloader.assert_called_once_with(
                "https://www.twitch.tv/videos/vod-1",
                root / "output" / "vod-1_chat.json",
            )

            transcript = json.loads(first.transcript_path.read_text(encoding="utf-8"))
            self.assertEqual(transcript[0]["words"][0]["start"], 1.0)
            timestamped_chat = json.loads(
                first.timestamped_chat_path.read_text(encoding="utf-8")
            )
            self.assertEqual(timestamped_chat[0]["timestamp"], 1.25)
            manifest = json.loads(
                (root / "output" / "vod-1_processing.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["stream_id"], "stream-1")
            self.assertEqual(manifest["vod_id"], "vod-1")
            self.assertEqual(manifest["clip_budget"], 10)
            self.assertTrue(manifest["transcription_complete"])
            self.assertTrue(manifest["chat_attempted"])

    def test_unavailable_chat_is_retried_and_succeeds_later(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            video_path = root / "vod-1.mp4"
            video_path.write_bytes(b"video")

            def download_chat(url: str, output_path: Path) -> Path:
                output_path.write_text('{"comments": []}', encoding="utf-8")
                return output_path

            calls = []

            def flaky(url, output_path):
                calls.append(url)
                if len(calls) == 1:
                    raise TwitchChatDownloadError("TwitchDownloaderCLI est introuvable dans le PATH.")
                return download_chat(url, output_path)

            pipeline = VODProcessingPipeline(
                output_dir=root / "output",
                transcriber=Mock(return_value=[]),
                chat_downloader=flaky,
            )

            first = pipeline.process(acquired_vod(video_path))
            second = pipeline.process(acquired_vod(video_path))
            third = pipeline.process(acquired_vod(video_path))
            manifest = json.loads(
                (root / "output" / "vod-1_processing.json").read_text(encoding="utf-8")
            )

        self.assertEqual(
            [first.chat_status, second.chat_status, third.chat_status],
            ["unavailable", "downloaded", "already_completed"],
        )
        self.assertEqual(len(calls), 2)  # valid chat never downloaded again
        self.assertEqual(manifest["chat_status"], "downloaded")
        self.assertNotIn("chat_error", manifest)

    def test_existing_raw_chat_is_reused_when_timestamps_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            video_path = root / "vod-1.mp4"
            video_path.write_bytes(b"video")
            output = root / "output"
            output.mkdir()
            (output / "vod-1_chat.json").write_text('{"comments": []}', encoding="utf-8")
            (output / "vod-1_processing.json").write_text(
                json.dumps({"chat_attempted": True, "chat_status": "unavailable"}),
                encoding="utf-8",
            )
            chat_downloader = Mock()
            result = VODProcessingPipeline(
                output_dir=output, transcriber=Mock(return_value=[]),
                chat_downloader=chat_downloader,
            ).process(acquired_vod(video_path))
            self.assertTrue((output / "vod-1_chat_timestamps.json").is_file())

        self.assertEqual(result.chat_status, "already_completed")
        chat_downloader.assert_not_called()

    def test_unavailable_chat_does_not_block_transcription(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            video_path = root / "vod-1.mp4"
            video_path.write_bytes(b"video")
            transcriber = Mock(return_value=[])
            chat_downloader = Mock(
                side_effect=TwitchChatDownloadError("chat replay unavailable")
            )
            pipeline = VODProcessingPipeline(
                output_dir=root / "output",
                transcriber=transcriber,
                chat_downloader=chat_downloader,
            )

            first = pipeline.process(acquired_vod(video_path))
            second = pipeline.process(acquired_vod(video_path))
            self.assertTrue(first.transcript_path.is_file())

        self.assertEqual(first.transcription_status, "completed")
        self.assertEqual(first.chat_status, "unavailable")
        self.assertEqual(second.transcription_status, "already_completed")
        self.assertEqual(second.chat_status, "unavailable")
        transcriber.assert_called_once()
        self.assertEqual(chat_downloader.call_count, 2)  # retried, still unavailable

    def test_failed_transcription_can_retry_without_redownloading_chat(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            video_path = root / "vod-1.mp4"
            video_path.write_bytes(b"video")
            transcriber = Mock(side_effect=[RuntimeError("model error"), []])

            def download_chat(url: str, output_path: Path) -> Path:
                output_path.write_text('{"comments": []}', encoding="utf-8")
                return output_path

            chat_downloader = Mock(side_effect=download_chat)
            pipeline = VODProcessingPipeline(
                output_dir=root / "output",
                transcriber=transcriber,
                chat_downloader=chat_downloader,
            )

            first = pipeline.process(acquired_vod(video_path))
            second = pipeline.process(acquired_vod(video_path))

        self.assertEqual(first.transcription_status, "error")
        self.assertEqual(first.chat_status, "downloaded")
        self.assertEqual(second.transcription_status, "completed")
        self.assertEqual(second.chat_status, "already_completed")
        self.assertEqual(transcriber.call_count, 2)
        chat_downloader.assert_called_once()

    def test_existing_artifacts_are_reused_after_manifest_write_interruption(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            video_path = root / "vod-1.mp4"
            video_path.write_bytes(b"video")
            output_dir = root / "output"
            output_dir.mkdir()
            (output_dir / "vod-1_transcript.json").write_text("[]", encoding="utf-8")
            (output_dir / "vod-1_chat.json").write_text(
                '{"comments": []}', encoding="utf-8"
            )
            transcriber = Mock()
            chat_downloader = Mock()
            pipeline = VODProcessingPipeline(
                output_dir=output_dir,
                transcriber=transcriber,
                chat_downloader=chat_downloader,
            )

            result = pipeline.process(acquired_vod(video_path))

        self.assertEqual(result.transcription_status, "already_completed")
        self.assertEqual(result.chat_status, "already_completed")
        transcriber.assert_not_called()
        chat_downloader.assert_not_called()


if __name__ == "__main__":
    unittest.main()