from pathlib import Path
import json
from datetime import datetime, timedelta, timezone
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

    @patch("twitch_auto_clipper.gemini_evaluation._get_gemini_client")
    def test_overloaded_model_falls_back_to_the_next_one(self, get_client) -> None:
        client = FakeGeminiClient(
            '{"evaluations":[{"candidate_id":"candidate_1","interesting":true,"score":70,"justification":"Ok."}]}'
        )
        models = []
        answer = client.generate_content

        def overloaded_first(**kwargs):
            models.append(kwargs["model"])
            if len(models) == 1:
                raise RuntimeError("503 UNAVAILABLE. This model is currently experiencing high demand.")
            return answer(**kwargs)

        client.generate_content = overloaded_first
        get_client.return_value = client
        [evaluation] = evaluate_candidates([{"start": 1.0, "end": 4.0}], [])
        self.assertEqual(models, ["gemini-3.6-flash", "gemini-3.8-flash"])
        self.assertEqual((evaluation["score"], evaluation["model"]), (70, "gemini-3.8-flash"))

    @patch("twitch_auto_clipper.gemini_evaluation._get_gemini_client")
    def test_daily_quota_is_counted_per_model_and_never_exceeded(self, get_client) -> None:
        client = FakeGeminiClient(
            '{"evaluations":[{"candidate_id":"candidate_1","interesting":true,"score":70,"justification":"Ok."}]}'
        )
        get_client.return_value = client
        with tempfile.TemporaryDirectory() as directory:
            options = {"quota_dir": Path(directory), "daily_limit": 1, "fallback_models": ("gemini-lite",)}
            evaluate_candidates([{"start": 1.0, "end": 4.0}], [], **options)
            evaluate_candidates([{"start": 1.0, "end": 4.0}], [], **options)
            self.assertEqual(client.arguments["model"], "gemini-lite")  # first model used up
            client.arguments = None
            with self.assertRaisesRegex(GeminiEvaluationError, "tous les modeles") as raised:
                evaluate_candidates([{"start": 1.0, "end": 4.0}], [], **options)
        self.assertIsNone(client.arguments)  # nothing sent beyond the limits
        self.assertIsNotNone(raised.exception.retry_at)

    @patch("twitch_auto_clipper.gemini_evaluation._get_gemini_client")
    def test_an_overloaded_model_does_not_spend_its_quota(self, get_client) -> None:
        from twitch_auto_clipper.daily_quota import DailyQuota

        client = FakeGeminiClient("")
        client.generate_content = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("503 UNAVAILABLE"))
        get_client.return_value = client
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(GeminiEvaluationError):
                evaluate_candidates([{"start": 1.0, "end": 4.0}], [], quota_dir=Path(directory),
                                    daily_limit=1, fallback_models=())
            self.assertTrue(DailyQuota(Path(directory) / "gemini_quota_gemini-3.6-flash.json", 1).available())

    @patch("twitch_auto_clipper.gemini_evaluation._get_gemini_client")
    def test_google_quota_refusal_closes_the_day_for_that_model(self, get_client) -> None:
        from twitch_auto_clipper.daily_quota import DailyQuota

        client = FakeGeminiClient("")
        client.generate_content = lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError("429 RESOURCE_EXHAUSTED quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier"))
        get_client.return_value = client
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(GeminiEvaluationError) as raised:
                evaluate_candidates([{"start": 1.0, "end": 4.0}], [], quota_dir=Path(directory),
                                    fallback_models=())
            self.assertFalse(DailyQuota(Path(directory) / "gemini_quota_gemini-3.6-flash.json", 20).available())
        self.assertGreater(raised.exception.retry_at - datetime.now(timezone.utc), timedelta(minutes=5))  # tomorrow

    @patch("twitch_auto_clipper.gemini_evaluation._get_gemini_client")
    def test_a_per_minute_limit_only_pauses_the_model_for_google_s_delay(self, get_client) -> None:
        from twitch_auto_clipper.daily_quota import DailyQuota

        client = FakeGeminiClient("")
        client.generate_content = lambda **kwargs: (_ for _ in ()).throw(RuntimeError(
            "429 RESOURCE_EXHAUSTED quotaId: GenerateContentInputTokensPerModelPerMinute-FreeTier, retryDelay: '30s'"))
        get_client.return_value = client
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(GeminiEvaluationError) as raised:
                evaluate_candidates([{"start": 1.0, "end": 4.0}], [], quota_dir=Path(directory),
                                    fallback_models=())
            quota = DailyQuota(Path(directory) / "gemini_quota_gemini-3.6-flash.json", 20)
            self.assertFalse(quota.available())
            self.assertIsNotNone(quota.paused_until())  # paused, not closed for the day
        self.assertLess(raised.exception.retry_at - datetime.now(timezone.utc), timedelta(minutes=1))

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
            quota_dir=None,
            daily_limit=20,
            streamer=None,
            examples="",
        )

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    @patch("twitch_auto_clipper.gemini_evaluation._get_gemini_client")
    def test_hook_and_description_are_kept_and_streamer_is_in_the_prompt(self, get_client) -> None:
        client = FakeGeminiClient(
            '{"evaluations":[{"candidate_id":"candidate_1","interesting":true,"score":80,'
            '"justification":"Fort.","hook":"  Wait for it 😱 ","title":" Chatterbox wins it all ","description":"He wins 🔥"}]}'
        )
        get_client.return_value = client
        [evaluation] = evaluate_candidates([{"start": 1.0, "end": 4.0}], [], streamer="Chatterbox, GTA V")
        self.assertEqual((evaluation["hook"], evaluation["description"]), ("Wait for it 😱", "He wins 🔥"))
        self.assertEqual(evaluation["title"], "Chatterbox wins it all")
        self.assertTrue(client.arguments["contents"].startswith("Streamer : Chatterbox, GTA V."))

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    @patch("twitch_auto_clipper.gemini_evaluation._get_gemini_client")
    def test_answer_for_every_candidate_keeps_the_best_within_budget(self, get_client) -> None:
        get_client.return_value = FakeGeminiClient(
            '{"evaluations":['
            '{"candidate_id":"candidate_1","interesting":false,"score":20,"justification":"Plat."},'
            '{"candidate_id":"candidate_2","interesting":true,"score":80,"justification":"Fort."},'
            '{"candidate_id":"candidate_3","interesting":true,"score":60,"justification":"Bien."}]}'
        )
        candidates = [{"start": i, "end": i + 1, "score": 1} for i in range(1, 4)]

        evaluations = evaluate_candidates(candidates, [], selection_count=2)
        self.assertEqual([e["candidate_id"] for e in evaluations], ["candidate_2", "candidate_3"])

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    @patch("twitch_auto_clipper.gemini_evaluation._get_gemini_client")
    def test_duplicate_selection_ids_are_kept_once(self, get_client) -> None:
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

        evaluations = evaluate_candidates(candidates, [], selection_count=2)
        self.assertEqual([e["candidate_id"] for e in evaluations], ["candidate_1"])  # duplicate dropped

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
