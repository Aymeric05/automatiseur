from pathlib import Path
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from twitch_auto_clipper.gemini_evaluation import (
    EVALUATION_RESPONSE_FORMAT,
    GeminiEvaluationError,
    evaluate_candidates,
    save_evaluations,
    select_candidate,
    select_candidates,
)


class FakeGeminiClient:
    def __init__(self, response_text: str) -> None:
        self.response_text = response_text
        self.interactions = self
        self.arguments = None

    def create(self, **kwargs):
        self.arguments = kwargs
        return SimpleNamespace(output_text=self.response_text)


class GeminiEvaluationTests(unittest.TestCase):
    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    @patch("twitch_auto_clipper.gemini_evaluation._get_gemini_client")
    def test_evaluate_candidates_returns_structured_evaluations(self, get_client) -> None:
        client = FakeGeminiClient(
            '{"evaluations":[{"candidate_id":"candidate_1",'
            '"interesting":true,"score":91,"justification":"Reaction forte."}]}'
        )
        get_client.return_value = client
        candidates = [
            {
                "start": 10.0,
                "end": 15.0,
                "score": 2.5,
                "chat_messages": 12,
                "chat_message_details": [
                    {"timestamp": 12.0, "text": "Pog!"}
                ],
            }
        ]
        transcription = [{"start": 10.0, "end": 15.0, "text": "No way!"}]

        evaluations = evaluate_candidates(candidates, transcription)

        self.assertEqual(evaluations[0]["candidate_id"], "candidate_1")
        self.assertEqual(evaluations[0]["score"], 91)
        self.assertIn("No way", client.arguments["input"])
        self.assertIn("chat_messages", client.arguments["input"])
        self.assertIn("Pog!", client.arguments["input"])
        self.assertEqual(client.arguments["model"], "gemini-3.6-flash")
        self.assertEqual(client.arguments["response_format"], EVALUATION_RESPONSE_FORMAT)
        self.assertEqual(
            client.arguments["response_format"]["mime_type"], "application/json"
        )
        self.assertEqual(
            client.arguments["response_format"]["schema"]["required"],
            ["evaluations"],
        )

    @patch.dict(os.environ, {}, clear=True)
    def test_evaluate_candidates_requires_api_key(self) -> None:
        with self.assertRaisesRegex(GeminiEvaluationError, "GEMINI_API_KEY"):
            evaluate_candidates([], [])

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    @patch("twitch_auto_clipper.gemini_evaluation._get_gemini_client")
    def test_evaluate_candidates_rejects_invalid_json(self, get_client) -> None:
        get_client.return_value = FakeGeminiClient("not json")

        with self.assertRaisesRegex(GeminiEvaluationError, "JSON invalide"):
            evaluate_candidates([], [])

    @patch("twitch_auto_clipper.gemini_evaluation.evaluate_candidates")
    def test_select_candidate_returns_zero_based_index(self, evaluate) -> None:
        evaluate.return_value = [
            {
                "candidate_id": "candidate_2",
                "interesting": True,
                "score": 95,
                "justification": "Moment fort.",
            }
        ]

        index, evaluation = select_candidate([{}, {}], [])

        self.assertEqual(index, 1)
        self.assertEqual(evaluation["candidate_id"], "candidate_2")

    @patch("twitch_auto_clipper.gemini_evaluation.evaluate_candidates")
    def test_select_candidate_rejects_invalid_selected_id(self, evaluate) -> None:
        evaluate.return_value = [
            {
                "candidate_id": "candidate_3",
                "interesting": True,
                "score": 95,
                "justification": "Moment fort.",
            }
        ]

        with self.assertRaisesRegex(GeminiEvaluationError, "inexistant"):
            select_candidate([{}, {}], [])

    def test_select_candidate_rejects_empty_candidates(self) -> None:
        with self.assertRaisesRegex(GeminiEvaluationError, "Aucun candidat"):
            select_candidate([], [])

    @patch("twitch_auto_clipper.gemini_evaluation.evaluate_candidates")
    def test_select_candidates_requests_budget_count_and_keeps_fewer_candidates(self, evaluate) -> None:
        evaluate.return_value = [
            {
                "candidate_id": "candidate_2",
                "interesting": True,
                "score": 90,
                "justification": "Moment marquant.",
            },
            {
                "candidate_id": "candidate_1",
                "interesting": True,
                "score": 85,
                "justification": "Reaction forte.",
            },
        ]

        selected = select_candidates([{}, {}], [], requested_count=5)

        self.assertEqual(len(selected), 2)
        evaluate.assert_called_once_with(
            [{}, {}], [], model="gemini-3.6-flash", selection_count=5
        )

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    @patch("twitch_auto_clipper.gemini_evaluation._get_gemini_client")
    def test_evaluate_candidates_rejects_wrong_selection_count(self, get_client) -> None:
        get_client.return_value = FakeGeminiClient(
            '{"evaluations":[{"candidate_id":"candidate_1",'
            '"interesting":true,"score":90,"justification":"Moment fort."}]}'
        )
        candidates = [
            {"start": 1, "end": 2, "score": 1},
            {"start": 3, "end": 4, "score": 1},
        ]

        with self.assertRaisesRegex(GeminiEvaluationError, "exactement 2"):
            evaluate_candidates(candidates, [], selection_count=2)

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    @patch("twitch_auto_clipper.gemini_evaluation._get_gemini_client")
    def test_evaluate_candidates_rejects_duplicate_selection_ids(self, get_client) -> None:
        evaluation = (
            '{"candidate_id":"candidate_1","interesting":true,'
            '"score":90,"justification":"Moment fort."}'
        )
        get_client.return_value = FakeGeminiClient(
            f'{{"evaluations":[{evaluation},{evaluation}]}}'
        )
        candidates = [
            {"start": 1, "end": 2, "score": 1},
            {"start": 3, "end": 4, "score": 1},
        ]

        with self.assertRaisesRegex(GeminiEvaluationError, "distincts"):
            evaluate_candidates(candidates, [], selection_count=2)

    def test_save_evaluations_writes_json(self) -> None:
        evaluations = [
            {
                "candidate_id": "candidate_1",
                "interesting": True,
                "score": 90,
                "justification": "Bon moment.",
            }
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "nested" / "gemini.json"
            save_evaluations(evaluations, output_path)
            saved = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(saved, evaluations)


if __name__ == "__main__":
    unittest.main()
