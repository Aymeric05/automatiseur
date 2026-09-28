"""Tests for the Gemini VOD highlight selection pipeline."""

from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from twitch_auto_clipper.vod_highlights import (
    VODHighlightSelectionResult,
    VODHighlightSelector,
    format_vod_highlight_selection,
)
from twitch_auto_clipper.vod_processing import VODProcessingResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_processed_vod(
    tmp: Path,
    *,
    vod_id: str = "vod_001",
    stream_id: str = "stream_001",
    clip_budget: int = 3,
    transcript: list | None = None,
    chat: list | None = None,
) -> VODProcessingResult:
    """Write fake transcript/chat files and return a VODProcessingResult."""
    if transcript is None:
        # Three high-scoring segments (reaction phrases score >0)
        transcript = [
            {"start": 0.0, "end": 10.0, "text": "No way! Insane clip!"},
            {"start": 20.0, "end": 30.0, "text": "Let's go! Amazing!"},
            {"start": 40.0, "end": 50.0, "text": "Incredible! Unbelievable!"},
        ]
    if chat is None:
        chat = []

    transcript_path = tmp / f"{vod_id}_transcript.json"
    chat_path = tmp / f"{vod_id}_chat.json"
    timestamped_chat_path = tmp / f"{vod_id}_chat_timestamps.json"

    transcript_path.write_text(json.dumps(transcript), encoding="utf-8")
    chat_path.write_text(json.dumps(chat), encoding="utf-8")
    timestamped_chat_path.write_text(json.dumps(chat), encoding="utf-8")

    return VODProcessingResult(
        stream_id=stream_id,
        vod_id=vod_id,
        broadcaster_id="broadcaster_001",
        broadcaster_login="broadcaster_login",
        broadcaster_name="Broadcaster Name",
        clip_budget=clip_budget,
        transcript_path=transcript_path,
        chat_path=chat_path,
        timestamped_chat_path=timestamped_chat_path,
        transcription_status="completed",
        chat_status="unavailable",
    )


def _fake_evaluations(candidates: list, count: int) -> list:
    """Return fake Gemini evaluations for the first `count` candidates."""
    return [
        {
            "candidate_id": f"candidate_{index + 1}",
            "interesting": True,
            "score": 90 - index,
            "justification": "Moment fort.",
        }
        for index in range(min(count, len(candidates)))
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class VODHighlightSelectorTests(unittest.TestCase):

    # ------------------------------------------------------------------
    # Exact count - budget == len(candidates)
    # ------------------------------------------------------------------

    @patch("twitch_auto_clipper.vod_highlights.select_candidates")
    def test_selects_exactly_clip_budget_candidates(self, mock_select) -> None:
        """When budget == len(candidates), exactly budget clips are selected."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            processed_vod = _make_processed_vod(tmp, clip_budget=3)
            mock_select.side_effect = lambda cands, trans, **kw: _fake_evaluations(
                cands, kw["requested_count"]
            )

            selector = VODHighlightSelector(output_dir=tmp)
            result = selector.select(processed_vod)

        self.assertEqual(result.status, "completed")
        self.assertEqual(len(result.selected), 3)
        self.assertEqual(result.clip_budget, 3)

    # ------------------------------------------------------------------
    # Fewer candidates than budget
    # ------------------------------------------------------------------

    @patch("twitch_auto_clipper.vod_highlights.select_candidates")
    def test_selects_all_candidates_when_budget_exceeds_candidate_count(
        self, mock_select
    ) -> None:
        """When budget > len(candidates), selected count == len(candidates)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            # Only 2 scorable segments, budget is 10
            transcript = [
                {"start": 0.0, "end": 10.0, "text": "No way! Insane!"},
                {"start": 20.0, "end": 30.0, "text": "Let's go!"},
            ]
            processed_vod = _make_processed_vod(
                tmp, clip_budget=10, transcript=transcript
            )
            # select_candidates must be called with the clamped count (2), not 10
            mock_select.side_effect = lambda cands, trans, **kw: _fake_evaluations(
                cands, kw["requested_count"]
            )

            selector = VODHighlightSelector(output_dir=tmp)
            result = selector.select(processed_vod)

        self.assertEqual(result.status, "completed")
        self.assertEqual(len(result.selected), 2)
        # Gemini was called with the clamped count, not the raw budget
        mock_select.assert_called_once()
        call_kwargs = mock_select.call_args.kwargs
        self.assertEqual(call_kwargs["requested_count"], 2)

    # ------------------------------------------------------------------
    # Zero budget
    # ------------------------------------------------------------------

    @patch("twitch_auto_clipper.vod_highlights.select_candidates")
    def test_zero_budget_skips_gemini_and_returns_empty_selection(
        self, mock_select
    ) -> None:
        """A clip_budget of 0 must return an empty selection without calling Gemini."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            processed_vod = _make_processed_vod(tmp, clip_budget=0)

            selector = VODHighlightSelector(output_dir=tmp)
            result = selector.select(processed_vod)

        self.assertEqual(result.status, "completed")
        self.assertEqual(len(result.selected), 0)
        mock_select.assert_not_called()

    # ------------------------------------------------------------------
    # Distinct candidate IDs enforced
    # ------------------------------------------------------------------

    @patch("twitch_auto_clipper.vod_highlights.select_candidates")
    def test_merge_selection_raises_on_duplicate_candidate_ids(
        self, mock_select
    ) -> None:
        """_merge_selection must raise GeminiEvaluationError on duplicate IDs."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            processed_vod = _make_processed_vod(tmp, clip_budget=2)
            # Gemini returns two items with the same candidate_id
            mock_select.return_value = [
                {
                    "candidate_id": "candidate_1",
                    "interesting": True,
                    "score": 90,
                    "justification": "Moment fort.",
                },
                {
                    "candidate_id": "candidate_1",  # duplicate
                    "interesting": True,
                    "score": 85,
                    "justification": "Reaction forte.",
                },
            ]

            selector = VODHighlightSelector(output_dir=tmp)
            result = selector.select(processed_vod)

        self.assertEqual(result.status, "error")
        self.assertIn("distincts", result.error)

    # ------------------------------------------------------------------
    # Resumability - valid existing selection is reused
    # ------------------------------------------------------------------

    @patch("twitch_auto_clipper.vod_highlights.select_candidates")
    def test_existing_valid_selection_is_reused_without_calling_gemini(
        self, mock_select
    ) -> None:
        """A complete selection JSON must be detected and reused (no Gemini call)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            vod_id = "vod_resume"
            transcript = [
                {"start": 0.0, "end": 10.0, "text": "No way! Insane!"},
            ]
            processed_vod = _make_processed_vod(
                tmp, vod_id=vod_id, stream_id="stream_001", clip_budget=1,
                transcript=transcript,
            )
            # Pre-write a valid selection file
            selected = [
                {
                    "start": 0.0,
                    "end": 10.0,
                    "score": 3.5,
                    "candidate_id": "candidate_1",
                    "gemini_interesting": True,
                    "gemini_score": 90,
                    "gemini_justification": "Moment fort.",
                }
            ]
            selection_path = tmp / f"{vod_id}_gemini_selection_1.json"
            selection_path.write_text(
                json.dumps(
                    {
                        "stream_id": "stream_001",
                        "vod_id": vod_id,
                        "broadcaster_id": "broadcaster_001",
                        "broadcaster_login": "broadcaster_login",
                        "broadcaster_name": "Broadcaster Name",
                        "clip_budget": 1,
                        "candidate_count": 1,
                        "requested_count": 1,
                        "model": "gemini-3.6-flash",
                        "selected": selected,
                    }
                ),
                encoding="utf-8",
            )

            selector = VODHighlightSelector(output_dir=tmp)
            result = selector.select(processed_vod)

        self.assertEqual(result.status, "already_completed")
        self.assertEqual(len(result.selected), 1)
        mock_select.assert_not_called()

    # ------------------------------------------------------------------
    # Resumability - corrupted or mismatched selection file is re-run
    # ------------------------------------------------------------------

    @patch("twitch_auto_clipper.vod_highlights.select_candidates")
    def test_mismatched_selection_json_triggers_fresh_gemini_call(
        self, mock_select
    ) -> None:
        """A selection file with a wrong vod_id must be ignored and re-run."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            vod_id = "vod_mismatch"
            processed_vod = _make_processed_vod(tmp, vod_id=vod_id, clip_budget=1)
            mock_select.side_effect = lambda cands, trans, **kw: _fake_evaluations(
                cands, kw["requested_count"]
            )
            # Write a selection file for a DIFFERENT vod
            selection_path = tmp / f"{vod_id}_gemini_selection_1.json"
            selection_path.write_text(
                json.dumps({"vod_id": "vod_other", "selected": []}),
                encoding="utf-8",
            )

            selector = VODHighlightSelector(output_dir=tmp)
            result = selector.select(processed_vod)

        self.assertEqual(result.status, "completed")
        mock_select.assert_called_once()

    # ------------------------------------------------------------------
    # Manifest updates - success path
    # ------------------------------------------------------------------

    @patch("twitch_auto_clipper.vod_highlights.select_candidates")
    def test_manifest_records_selection_file_path_on_success(
        self, mock_select
    ) -> None:
        """On success, the manifest must record the selection file under gemini_selection_files."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            vod_id = "vod_manifest"
            processed_vod = _make_processed_vod(tmp, vod_id=vod_id, clip_budget=1)
            mock_select.side_effect = lambda cands, trans, **kw: _fake_evaluations(
                cands, kw["requested_count"]
            )
            manifest_path = tmp / f"{vod_id}_processing.json"
            manifest_path.write_text("{}", encoding="utf-8")

            selector = VODHighlightSelector(output_dir=tmp)
            result = selector.select(processed_vod)

            self.assertEqual(result.status, "completed")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertIn("gemini_selection_files", manifest)
            self.assertEqual(
                manifest["gemini_selection_files"]["1"],
                f"{vod_id}_gemini_selection_1.json",
            )
            self.assertNotIn("gemini_selection_error", manifest)

    # ------------------------------------------------------------------
    # Manifest updates - error path
    # ------------------------------------------------------------------

    @patch("twitch_auto_clipper.vod_highlights.select_candidates")
    def test_manifest_records_error_on_gemini_failure(self, mock_select) -> None:
        """On Gemini failure, the manifest must record gemini_selection_error."""
        from twitch_auto_clipper.gemini_evaluation import GeminiEvaluationError

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            vod_id = "vod_err"
            processed_vod = _make_processed_vod(tmp, vod_id=vod_id, clip_budget=1)
            mock_select.side_effect = GeminiEvaluationError("Gemini timeout")
            manifest_path = tmp / f"{vod_id}_processing.json"
            manifest_path.write_text("{}", encoding="utf-8")

            selector = VODHighlightSelector(output_dir=tmp)
            result = selector.select(processed_vod)

            self.assertEqual(result.status, "error")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertIn("gemini_selection_error", manifest)
            self.assertIn("Gemini timeout", manifest["gemini_selection_error"])
            self.assertNotIn("gemini_selection_files", manifest)

    # ------------------------------------------------------------------
    # Error handling - bad transcript
    # ------------------------------------------------------------------

    def test_missing_transcript_returns_error_status(self) -> None:
        """A missing transcript file must return status='error'."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            processed_vod = _make_processed_vod(tmp, clip_budget=1)
            # Delete the transcript file
            processed_vod.transcript_path.unlink()

            selector = VODHighlightSelector(output_dir=tmp)
            result = selector.select(processed_vod)

        self.assertEqual(result.status, "error")
        self.assertIsNotNone(result.error)

    # ------------------------------------------------------------------
    # Selection file content - candidate_ids are valid and distinct
    # ------------------------------------------------------------------

    @patch("twitch_auto_clipper.vod_highlights.select_candidates")
    def test_saved_selection_has_valid_distinct_candidate_ids(
        self, mock_select
    ) -> None:
        """The persisted selection JSON must contain distinct, valid candidate_ids."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            processed_vod = _make_processed_vod(tmp, clip_budget=2)
            mock_select.side_effect = lambda cands, trans, **kw: _fake_evaluations(
                cands, kw["requested_count"]
            )

            selector = VODHighlightSelector(output_dir=tmp)
            result = selector.select(processed_vod)

            self.assertEqual(result.status, "completed")
            saved = json.loads(result.selection_path.read_text(encoding="utf-8"))
            ids = [item["candidate_id"] for item in saved["selected"]]
            # All IDs must be unique
            self.assertEqual(len(ids), len(set(ids)))
            # All IDs must be in the valid candidate_N format
            for candidate_id in ids:
                self.assertRegex(candidate_id, r"^candidate_\d+$")


# ---------------------------------------------------------------------------
# format_vod_highlight_selection
# ---------------------------------------------------------------------------

class FormatVODHighlightSelectionTests(unittest.TestCase):
    def _result(self, status: str, error: str | None = None) -> VODHighlightSelectionResult:
        return VODHighlightSelectionResult(
            stream_id="stream_001",
            vod_id="vod_001",
            clip_budget=3,
            candidate_count=5,
            selected=(),
            selection_path=Path("data/output/vod_001_gemini_selection_3.json"),
            candidate_path=Path("data/output/vod_001_highlights.json"),
            status=status,
            error=error,
        )

    def test_format_error_result(self) -> None:
        result = self._result("error", "Gemini timeout")
        text = format_vod_highlight_selection(result)
        self.assertIn("Erreur", text)
        self.assertIn("vod_001", text)
        self.assertIn("Gemini timeout", text)

    def test_format_completed_result(self) -> None:
        result = self._result("completed")
        text = format_vod_highlight_selection(result)
        self.assertIn("vod_001", text)
        self.assertIn("3", text)


if __name__ == "__main__":
    unittest.main()
