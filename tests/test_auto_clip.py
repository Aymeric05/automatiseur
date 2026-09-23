from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

from twitch_auto_clipper.candidate_clip import CandidateClipError
from twitch_auto_clipper.cli import main


class AutoClipCliTests(unittest.TestCase):
    @patch("twitch_auto_clipper.cli.generate_clip_from_candidate")
    @patch("twitch_auto_clipper.cli.select_candidate")
    def test_auto_clip_sends_selected_index_to_candidate_orchestrator(
        self, select_candidate, generate_clip
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source.mp4"
            candidates = root / "highlights.json"
            transcript = root / "transcript.json"
            source.write_bytes(b"video")
            candidates.write_text(
                json.dumps([{"start": 1, "end": 3}, {"start": 10, "end": 12}]),
                encoding="utf-8",
            )
            transcript.write_text("[]", encoding="utf-8")
            select_candidate.return_value = (
                1,
                {"candidate_id": "candidate_2", "score": 90},
            )
            generate_clip.return_value = (root / "clip.mp4", 5.0, 17.0)
            arguments = [
                "twitch_auto_clipper",
                "--auto-clip",
                "--candidates-json",
                str(candidates),
                "--transcript-json",
                str(transcript),
                "--source",
                str(source),
            ]
            with patch.object(sys, "argv", arguments):
                result = main()

        self.assertEqual(result, 0)
        self.assertEqual(generate_clip.call_args.args[2], 1)
        self.assertEqual(generate_clip.call_args.kwargs["before"], 5.0)
        self.assertEqual(generate_clip.call_args.kwargs["after"], 5.0)

    @patch("twitch_auto_clipper.cli.select_candidate")
    def test_auto_clip_reports_generation_error(self, select_candidate) -> None:
        select_candidate.side_effect = CandidateClipError("Erreur de clip")
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source.mp4"
            candidates = root / "highlights.json"
            transcript = root / "transcript.json"
            source.write_bytes(b"video")
            candidates.write_text("[]", encoding="utf-8")
            transcript.write_text("[]", encoding="utf-8")
            arguments = [
                "twitch_auto_clipper",
                "--auto-clip",
                "--candidates-json",
                str(candidates),
                "--transcript-json",
                str(transcript),
                "--source",
                str(source),
            ]
            with patch.object(sys, "argv", arguments):
                result = main()

        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
