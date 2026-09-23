from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from twitch_auto_clipper.candidate_clip import (
    CandidateClipError,
    calculate_candidate_bounds,
    generate_clip_from_candidate,
    load_candidate,
)


class CandidateClipTests(unittest.TestCase):
    def test_calculate_candidate_bounds_applies_margins_and_clamps_duration(self) -> None:
        start, end = calculate_candidate_bounds(
            {"start": 26, "end": 40}, duration=30, before=5, after=5
        )

        self.assertEqual((start, end), (21.0, 30.0))

    def test_calculate_candidate_bounds_rejects_invalid_margin(self) -> None:
        with self.assertRaisesRegex(CandidateClipError, "marges"):
            calculate_candidate_bounds({"start": 1, "end": 2}, 10, before=-1)

    def test_load_candidate_validates_index_and_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "highlights.json"
            path.write_text(json.dumps([{"start": 1, "end": 2}]), encoding="utf-8")

            self.assertEqual(load_candidate(path, 0)["start"], 1)
            with self.assertRaises(CandidateClipError):
                load_candidate(path, 2)

    @patch("twitch_auto_clipper.candidate_clip.create_vertical_clip")
    @patch("twitch_auto_clipper.candidate_clip.get_video_duration", return_value=30.0)
    def test_generate_clip_from_candidate_uses_clamped_bounds_and_subtitles(
        self, get_duration, create_clip
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source.mp4"
            candidates = root / "highlights.json"
            transcript = root / "transcript.json"
            output = root / "output.mp4"
            source.write_bytes(b"video")
            candidates.write_text(
                json.dumps([{"start": 26, "end": 40}]), encoding="utf-8"
            )
            transcript.write_text(
                json.dumps(
                    [
                        {
                            "words": [
                                {"word": "test", "start": 26, "end": 27}
                            ]
                        }
                    ]
                ),
                encoding="utf-8",
            )

            result = generate_clip_from_candidate(
                source, candidates, 0, output, transcript_path=transcript
            )

        self.assertEqual(result[1:], (21.0, 30.0))
        create_clip.assert_called_once()
        self.assertEqual(create_clip.call_args.args[2:4], (21.0, 30.0))
        self.assertIsNotNone(create_clip.call_args.kwargs["subtitles_path"])
        get_duration.assert_called_once_with(source)


if __name__ == "__main__":
    unittest.main()
