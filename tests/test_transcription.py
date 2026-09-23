from pathlib import Path
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from twitch_auto_clipper.transcription import save_transcription, transcribe_video


class FakeWhisperModel:
    def __init__(self, model_size: str, device: str, compute_type: str) -> None:
        self.arguments = (model_size, device, compute_type)

    def transcribe(self, input_path: str, **options):
        self.arguments = (input_path, options)
        return (
            [
                SimpleNamespace(
                    start=1.5,
                    end=3.0,
                    text=" Bonjour ",
                    words=[
                        SimpleNamespace(word=" Bonjour ", start=1.5, end=2.2),
                    ],
                )
            ],
            SimpleNamespace(language="fr"),
        )


class TranscriptionTests(unittest.TestCase):
    @patch("twitch_auto_clipper.transcription._get_whisper_model")
    def test_transcribe_video_returns_segment_and_word_timestamps(self, get_model) -> None:
        model = FakeWhisperModel("base", "cpu", "int8")
        get_model.return_value = model

        with tempfile.TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory) / "video.mp4"
            input_path.write_bytes(b"video")
            segments = transcribe_video(input_path, language="fr")

        get_model.assert_called_once_with("base", "cpu", "int8")
        self.assertEqual(segments[0]["start"], 1.5)
        self.assertEqual(segments[0]["end"], 3.0)
        self.assertEqual(segments[0]["text"], "Bonjour")
        self.assertEqual(segments[0]["words"][0]["start"], 1.5)
        self.assertEqual(model.arguments[1]["word_timestamps"], True)
        self.assertEqual(model.arguments[1]["language"], "fr")

    @patch("twitch_auto_clipper.transcription._get_whisper_model")
    def test_transcribe_video_allows_custom_device_and_compute_type(self, get_model) -> None:
        model = FakeWhisperModel("small", "cuda", "float16")
        get_model.return_value = model

        with tempfile.TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory) / "video.mp4"
            input_path.write_bytes(b"video")
            transcribe_video(
                input_path,
                model_size="small",
                device="cuda",
                compute_type="float16",
            )

        get_model.assert_called_once_with("small", "cuda", "float16")

    def test_save_transcription_writes_json(self) -> None:
        segments = [{"start": 0.0, "end": 1.0, "text": "Bonjour", "words": []}]

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "nested" / "transcript.json"
            save_transcription(segments, output_path)
            saved = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(saved, segments)


if __name__ == "__main__":
    unittest.main()
