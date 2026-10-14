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
        self.assertTrue(model.arguments[1]["vad_filter"])  # no invented text over music/silence

    @patch("twitch_auto_clipper.transcription._extract_chunk")
    @patch("twitch_auto_clipper.transcription._duration", return_value=25.0)
    @patch("twitch_auto_clipper.transcription._get_whisper_model")
    def test_long_files_are_transcribed_in_chunks_with_absolute_times(
        self, get_model, duration, extract
    ) -> None:
        model = FakeWhisperModel("base", "cpu", "int8")
        get_model.return_value = model

        with tempfile.TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory) / "vod_audio.mp4"
            input_path.write_bytes(b"audio")
            segments = transcribe_video(input_path, chunk_seconds=10)

        self.assertEqual([call.args[1:3] for call in extract.call_args_list], [(0.0, 10), (10.0, 10), (20.0, 10)])
        self.assertEqual([segment["start"] for segment in segments], [1.5, 11.5, 21.5])
        self.assertEqual(segments[1]["words"][0]["start"], 11.5)

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

    @patch("twitch_auto_clipper.transcription._get_whisper_model")
    def test_auto_uses_the_gpu_model_when_cuda_works_and_the_cpu_otherwise(self, get_model) -> None:
        get_model.return_value = FakeWhisperModel("x", "x", "x")
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory) / "audio.mp4"
            input_path.write_bytes(b"audio")
            with patch("twitch_auto_clipper.transcription.cuda_available", return_value=True):
                transcribe_video(input_path, device="auto")
            self.assertEqual(get_model.call_args.args, ("small", "cuda", "float16"))
            with patch("twitch_auto_clipper.transcription.cuda_available", return_value=False):
                transcribe_video(input_path, device="auto")
            self.assertEqual(get_model.call_args.args, ("base", "cpu", "int8"))

    @patch("twitch_auto_clipper.transcription._get_whisper_model")
    def test_gpu_failure_falls_back_to_the_cpu(self, get_model) -> None:
        def load(model_size, device, compute_type):
            if device == "cuda":
                raise RuntimeError("CUDA out of memory")
            return FakeWhisperModel(model_size, device, compute_type)

        get_model.side_effect = load
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory) / "audio.mp4"
            input_path.write_bytes(b"audio")
            with patch("twitch_auto_clipper.transcription.cuda_available", return_value=True):
                segments = transcribe_video(input_path, device="auto")
        self.assertEqual(segments[0]["text"], "Bonjour")
        self.assertEqual(get_model.call_args.args, ("base", "cpu", "int8"))

    def test_save_transcription_writes_json(self) -> None:
        segments = [{"start": 0.0, "end": 1.0, "text": "Bonjour", "words": []}]

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "nested" / "transcript.json"
            save_transcription(segments, output_path)
            saved = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(saved, segments)


if __name__ == "__main__":
    unittest.main()
