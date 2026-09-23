from pathlib import Path
import json
import tempfile
import unittest

from twitch_auto_clipper.highlights import (
    HighlightAnalysisError,
    analyze_transcription,
    load_transcription,
    save_highlights,
)


class HighlightTests(unittest.TestCase):
    def test_analyze_transcription_scores_reactions_and_punctuation(self) -> None:
        segments = [
            {"start": 10, "end": 15, "text": "Oh my god!!! What happened?"},
            {"start": 20, "end": 24, "text": "Une phrase ordinaire."},
        ]

        candidates = analyze_transcription(segments)

        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0]["start"], 10.0)
        self.assertGreater(candidates[0]["score"], candidates[1]["score"])

    def test_analyze_transcription_scores_repeated_words(self) -> None:
        candidates = analyze_transcription(
            [{"start": 0, "end": 4, "text": "Non non non, c'est incroyable!"}]
        )

        self.assertEqual(len(candidates), 1)
        self.assertGreaterEqual(candidates[0]["score"], 3.0)

    def test_analyze_transcription_can_limit_candidates(self) -> None:
        segments = [
            {"start": 0, "end": 4, "text": "Wow!"},
            {"start": 10, "end": 14, "text": "No way!"},
        ]

        candidates = analyze_transcription(segments, max_candidates=1)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["start"], 10.0)

    def test_transcription_json_can_be_loaded_and_saved(self) -> None:
        segments = [{"start": 1, "end": 2, "text": "Wow!", "words": []}]
        candidates = analyze_transcription(segments)

        with tempfile.TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory) / "transcript.json"
            output_path = Path(temporary_directory) / "highlights.json"
            input_path.write_text(json.dumps(segments), encoding="utf-8")

            self.assertEqual(load_transcription(input_path), segments)
            save_highlights(candidates, output_path)
            saved = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(saved, candidates)

    def test_load_transcription_rejects_non_list_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory) / "invalid.json"
            input_path.write_text("{}", encoding="utf-8")

            with self.assertRaises(HighlightAnalysisError):
                load_transcription(input_path)


if __name__ == "__main__":
    unittest.main()
