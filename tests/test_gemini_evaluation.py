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
        self.models = self
        self.arguments = None

    def generate_content(self, **kwargs):
        self.arguments = kwargs
        return SimpleNamespace(text=self.response_text)


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
                    {"timestamp": 12.0, "text": "raw message never sent"}
                ],
                "chat_signal": {
                    "messages": 12, "rate": 1.2, "activity_ratio": 2.5, "distinct_authors": 11,
                    "laugh_ratio": 0.4, "short_reaction_ratio": 0.2, "top_reactions": [["lol", 4]],
                    "sample_messages": ["Pog! what a play"], "reliable": True,
                },
            }
        ]
        transcription = [
            {"start": 0.0, "end": 9.0, "text": "Watch this."},
            {"start": 10.0, "end": 15.0, "text": "No way!"},
            {"start": 16.0, "end": 20.0, "text": "I told you."},
        ]

        evaluations = evaluate_candidates(candidates, transcription)

        self.assertEqual(evaluations[0]["candidate_id"], "candidate_1")
        self.assertEqual(evaluations[0]["score"], 91)
        self.assertIn("No way", client.arguments["contents"])
        prompt = client.arguments["contents"]
        [sent], _ = json.JSONDecoder().raw_decode(prompt.split("\n\n", 1)[1])
        self.assertEqual(sent["transcript"], "No way!")
        self.assertEqual((sent["context_before"], sent["context_after"]), ("Watch this.", "I told you."))
        self.assertEqual(sent["chat"]["top_reactions"], [["lol", 4]])
        self.assertEqual(sent["chat"]["sample_messages"], ["Pog! what a play"])
        self.assertTrue(sent["chat"]["reliable"])
        self.assertNotIn("raw message never sent", prompt)  # compact summary only

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    @patch("twitch_auto_clipper.gemini_evaluation._get_gemini_client")
    def test_candidates_without_chat_send_null_chat(self, get_client) -> None:
        client = FakeGeminiClient(
            '{"evaluations":[{"candidate_id":"candidate_1",'
            '"interesting":false,"score":10,"justification":"Plat."}]}'
        )
        get_client.return_value = client
        evaluate_candidates([{"start": 1.0, "end": 4.0, "score": 1}], [])
        self.assertIn('"chat": null', client.arguments["contents"])
        self.assertEqual(client.arguments["model"], "gemini-3.6-flash")
        config = client.arguments["config"]
        self.assertEqual(config["response_json_schema"], EVALUATION_RESPONSE_FORMAT["schema"])
        self.assertEqual(
            config["response_mime_type"], "application/json"
        )
        self.assertEqual(
            config["response_json_schema"]["required"],
            ["evaluations"],
        )

    @patch("twitch_auto_clipper.gemini_evaluation.time.sleep")
    @patch("twitch_auto_clipper.gemini_evaluation._get_gemini_client")
    def test_transient_unavailability_is_retried_but_quota_is_not(self, get_client, sleep) -> None:
        client = FakeGeminiClient(
            '{"evaluations":[{"candidate_id":"candidate_1","interesting":true,"score":70,"justification":"Ok."}]}'
        )
        calls = []
        answer = client.generate_content

        def flaky(**kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("503 UNAVAILABLE. This model is currently experiencing high demand.")
            return answer(**kwargs)

        client.generate_content = flaky
        get_client.return_value = client
        evaluations = evaluate_candidates([{"start": 1.0, "end": 4.0}], [])
        self.assertEqual((len(calls), evaluations[0]["score"]), (2, 70))
        sleep.assert_called_once()

        def quota(**kwargs):
            raise RuntimeError("429 RESOURCE_EXHAUSTED")

        client.generate_content = quota
        sleep.reset_mock()
        with self.assertRaisesRegex(GeminiEvaluationError, "429"):
            evaluate_candidates([{"start": 1.0, "end": 4.0}], [])
        sleep.assert_not_called()

    @patch("twitch_auto_clipper.gemini_evaluation._get_gemini_client")
    def test_daily_quota_counts_requests_and_stops_before_the_limit(self, get_client) -> None:
        from twitch_auto_clipper.daily_quota import DailyQuota

        client = FakeGeminiClient(
            '{"evaluations":[{"candidate_id":"candidate_1","interesting":true,"score":70,"justification":"Ok."}]}'
        )
        get_client.return_value = client
        with tempfile.TemporaryDirectory() as directory:
            quota = DailyQuota(Path(directory) / "gemini.json", daily_limit=1)
            evaluate_candidates([{"start": 1.0, "end": 4.0}], [], quota=quota)
            client.arguments = None
            with self.assertRaisesRegex(GeminiEvaluationError, "Quota Gemini du jour") as raised:
                evaluate_candidates([{"start": 1.0, "end": 4.0}], [], quota=quota)
        self.assertIsNone(client.arguments)  # no request sent beyond the limit
        self.assertEqual(raised.exception.retry_at, quota.next_reset())

    @patch("twitch_auto_clipper.gemini_evaluation._get_gemini_client")
    def test_google_quota_refusal_closes_the_day(self, get_client) -> None:
        from twitch_auto_clipper.daily_quota import DailyQuota

        client = FakeGeminiClient("")
        client.generate_content = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("429 RESOURCE_EXHAUSTED"))
        get_client.return_value = client
        with tempfile.TemporaryDirectory() as directory:
            quota = DailyQuota(Path(directory) / "gemini.json", daily_limit=20)
            with self.assertRaises(GeminiEvaluationError) as raised:
                evaluate_candidates([{"start": 1.0, "end": 4.0}], [], quota=quota)
            self.assertFalse(quota.available())
        self.assertIsNotNone(raised.exception.retry_at)

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
            [{}, {}], [], model="gemini-3.6-flash", selection_count=5,
            quota=None,
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


    def test_candidate_context_includes_what_is_said_around_the_clip(self) -> None:
        from twitch_auto_clipper.gemini_evaluation import _candidate_context

        transcription = [
            {"start": 3, "end": 8, "text": "Earlier setup."},
            {"start": 20, "end": 30, "text": "The actual moment."},
            {"start": 32, "end": 36, "text": "The reaction after."},
            {"start": 80, "end": 85, "text": "Unrelated later talk."},
        ]
        [context] = _candidate_context([{"start": 20, "end": 30, "score": 3}], transcription)
        self.assertEqual(context["transcript"], "The actual moment.")
        self.assertEqual(context["context_before"], "Earlier setup.")
        self.assertEqual(context["context_after"], "The reaction after.")
        self.assertEqual(context["duration"], 10.0)


if __name__ == "__main__":
    unittest.main()
