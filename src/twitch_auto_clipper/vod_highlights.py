"""Gemini highlight selection for processed Twitch VODs."""

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from .chat_activity import add_chat_messages, add_chat_signals, chat_spike_moments
from .gemini_evaluation import GeminiEvaluationError, select_candidates
from .highlights import HighlightAnalysisError, _overlap_ratio, analyze_transcription, save_highlights
from .vod_processing import VODProcessingResult

MAX_GEMINI_CANDIDATES = 30  # best heuristic candidates sent to Gemini
# A top streamer's VOD (budget 20): twice the moments to choose its 20 Shorts from.
TOP_GEMINI_CANDIDATES = 60
CHAT_CANDIDATE_SHARE = 3  # at most 1/3 of the candidates come from chat spikes
EMOTION_CANDIDATE_SHARE = 6  # at most 1/6 from laughter, screams... found in the audio
MAX_CANDIDATE_OVERLAP = 0.25  # an added moment must be new, not one already listed


@dataclass(frozen=True)
class VODHighlightSelectionResult:
    stream_id: str
    vod_id: str
    clip_budget: int
    candidate_count: int
    selected: tuple[dict[str, Any], ...]
    selection_path: Path
    candidate_path: Path
    status: str
    error: str | None = None
    retry_at: datetime | None = None  # error caused only by the Gemini daily quota


class VODHighlightSelector:
    """Select and persist up to the assigned clip budget for a processed VOD."""

    def __init__(
        self,
        output_dir: Path = Path("data/output"),
        model: str = "gemini-3.6-flash",
        gemini_daily_limit: int | None = None,
    ) -> None:
        self.output_dir = output_dir
        self.model = model
        # Requests per Gemini model and per day (free tier), counted in output_dir.
        self.gemini_daily_limit = gemini_daily_limit

    def select(self, processed_vod: VODProcessingResult) -> VODHighlightSelectionResult:
        vod_id = processed_vod.vod_id
        budget = processed_vod.clip_budget
        candidate_path = self.output_dir / f"{vod_id}_highlights.json"
        selection_path = self.output_dir / f"{vod_id}_gemini_selection_{budget}.json"
        manifest_path = self.output_dir / f"{vod_id}_processing.json"

        try:
            transcript = self._load_json_list(processed_vod.transcript_path)
            max_candidates = TOP_GEMINI_CANDIDATES if budget >= 20 else MAX_GEMINI_CANDIDATES
            candidates = analyze_transcription(transcript, max_candidates=max_candidates)
            chat_messages = self._load_optional_list(processed_vod.timestamped_chat_path)
            emotions = [
                moment for moment in self._load_optional_list(processed_vod.emotions_path)
                if isinstance(moment, dict) and isinstance(moment.get("emotion"), str)
                and all(isinstance(moment.get(key), (int, float)) for key in ("start", "end"))
            ]
            # Moments the transcript missed, in place of its last candidates: up to a
            # third from chat spikes, up to a sixth from laughter, screams... in the audio.
            limit = max_candidates // CHAT_CANDIDATE_SHARE
            added = new_moments(chat_spike_moments(chat_messages, limit=limit), candidates, limit)
            added += new_moments(emotions, candidates + added, max_candidates // EMOTION_CANDIDATE_SHARE)
            candidates = tag_emotions(candidates[: max_candidates - len(added)] + added, emotions)
            if chat_messages:
                candidates = add_chat_signals(add_chat_messages(candidates, chat_messages), chat_messages)
            else:
                candidates = [
                    {
                        **candidate,
                        "chat_messages": 0,
                        "chat_message_details": [],
                    }
                    for candidate in candidates
                ]
            save_highlights(candidates, candidate_path)
        except (HighlightAnalysisError, OSError, ValueError, json.JSONDecodeError) as error:
            return self._result(
                processed_vod,
                len(candidates) if "candidates" in locals() else 0,
                (),
                selection_path,
                candidate_path,
                "error",
                str(error),
            )

        existing_selection = self._load_valid_selection(
            selection_path,
            processed_vod,
            len(candidates),
        )
        if existing_selection is not None:
            self._record_selection(manifest_path, budget, selection_path, None)
            return self._result(
                processed_vod,
                len(candidates),
                tuple(existing_selection),
                selection_path,
                candidate_path,
                "already_completed",
            )

        requested_count = min(max(0, budget), len(candidates))
        try:
            evaluations = (
                select_candidates(
                    candidates,
                    transcript,
                    requested_count=requested_count,
                    model=self.model,
                    quota_dir=self.output_dir if self.gemini_daily_limit else None,
                    daily_limit=self.gemini_daily_limit or 20,
                    streamer=", ".join(
                        filter(None, (processed_vod.broadcaster_name, processed_vod.game_name))
                    ),
                )
                if requested_count
                else []
            )
            selected = self._merge_selection(candidates, evaluations, requested_count)
            payload = {
                "stream_id": processed_vod.stream_id,
                "vod_id": vod_id,
                "broadcaster_id": processed_vod.broadcaster_id,
                "broadcaster_login": processed_vod.broadcaster_login,
                "broadcaster_name": processed_vod.broadcaster_name,
                "clip_budget": budget,
                "candidate_count": len(candidates),
                "requested_count": requested_count,
                "model": self.model,
                "selected": selected,
            }
            self._write_json_atomic(selection_path, payload)
            self._record_selection(manifest_path, budget, selection_path, None)
        except (GeminiEvaluationError, OSError, ValueError) as error:
            self._record_selection(manifest_path, budget, None, str(error))
            return self._result(
                processed_vod,
                len(candidates),
                (),
                selection_path,
                candidate_path,
                "error",
                str(error),
                retry_at=getattr(error, "retry_at", None),
            )

        return self._result(
            processed_vod,
            len(candidates),
            tuple(selected),
            selection_path,
            candidate_path,
            "completed",
        )

    @staticmethod
    def _load_json_list(path: Path) -> list[dict[str, Any]]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise HighlightAnalysisError(f"Impossible de lire {path}") from error
        if not isinstance(data, list):
            raise HighlightAnalysisError(f"Le fichier doit contenir une liste : {path}")
        return data

    @staticmethod
    def _load_optional_list(path: Path | None) -> list[dict[str, Any]]:
        try:
            messages = json.loads(path.read_text(encoding="utf-8"))
        except (AttributeError, OSError, json.JSONDecodeError):  # AttributeError: no path
            return []
        return messages if isinstance(messages, list) else []

    @classmethod
    def _load_valid_selection(
        cls,
        path: Path,
        processed_vod: VODProcessingResult,
        candidate_count: int,
    ) -> list[dict[str, Any]] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        expected_count = min(max(0, processed_vod.clip_budget), candidate_count)
        selected = payload.get("selected")
        if (
            payload.get("vod_id") != processed_vod.vod_id
            or payload.get("stream_id") != processed_vod.stream_id
            or payload.get("clip_budget") != processed_vod.clip_budget
            or payload.get("candidate_count") != candidate_count
            or payload.get("requested_count") != expected_count
            or not isinstance(selected, list)
            or len(selected) > expected_count
        ):
            return None
        candidate_ids = [item.get("candidate_id") for item in selected if isinstance(item, dict)]
        if len(candidate_ids) != len(selected) or len(set(candidate_ids)) != len(selected):
            return None
        valid_ids = {f"candidate_{index}" for index in range(1, candidate_count + 1)}
        if any(candidate_id not in valid_ids for candidate_id in candidate_ids):
            return None
        if any(
            not isinstance(item.get("start"), (int, float))
            or not isinstance(item.get("end"), (int, float))
            for item in selected
        ):
            return None
        return selected

    @staticmethod
    def _merge_selection(
        candidates: list[dict[str, Any]],
        evaluations: list[dict[str, Any]],
        requested_count: int,
    ) -> list[dict[str, Any]]:
        candidate_ids = [item.get("candidate_id") for item in evaluations]
        if len(evaluations) > requested_count or len(set(candidate_ids)) != len(evaluations):
            raise GeminiEvaluationError(
                f"Gemini doit retourner au plus {requested_count} candidats distincts."
            )

        selected = []
        for evaluation in evaluations:
            candidate_id = evaluation["candidate_id"]
            try:
                candidate_index = int(candidate_id.removeprefix("candidate_")) - 1
            except (AttributeError, ValueError) as error:
                raise GeminiEvaluationError("Gemini a retourne un candidat invalide.") from error
            if candidate_index < 0 or candidate_index >= len(candidates):
                raise GeminiEvaluationError("Gemini a retourne un candidat inexistant.")
            selected.append(
                {
                    **candidates[candidate_index],
                    "candidate_id": candidate_id,
                    "gemini_interesting": evaluation["interesting"],
                    "gemini_score": evaluation["score"],
                    "gemini_justification": evaluation["justification"],
                    "gemini_model": evaluation.get("model"),
                    "gemini_hook": evaluation.get("hook") or None,
                    "gemini_title": evaluation.get("title") or None,
                    "gemini_description": evaluation.get("description") or None,
                }
            )
        return selected

    def _record_selection(
        self,
        manifest_path: Path,
        budget: int,
        selection_path: Path | None,
        error: str | None,
    ) -> None:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            manifest = {}
        except (OSError, json.JSONDecodeError) as manifest_error:
            raise ValueError(f"Unable to update VOD manifest: {manifest_error}") from manifest_error
        if not isinstance(manifest, dict):
            raise ValueError("VOD manifest has an invalid format.")

        if selection_path is not None:
            files = manifest.setdefault("gemini_selection_files", {})
            if not isinstance(files, dict):
                files = {}
                manifest["gemini_selection_files"] = files
            files[str(budget)] = selection_path.name
            manifest.pop("gemini_selection_error", None)
        elif error is not None:
            manifest["gemini_selection_error"] = error
        self._write_json_atomic(manifest_path, manifest)

    @staticmethod
    def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f"{path.name}.tmp")
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(path)

    @staticmethod
    def _result(
        processed_vod: VODProcessingResult,
        candidate_count: int,
        selected: tuple[dict[str, Any], ...],
        selection_path: Path,
        candidate_path: Path,
        status: str,
        error: str | None = None,
        retry_at: datetime | None = None,
    ) -> VODHighlightSelectionResult:
        return VODHighlightSelectionResult(
            stream_id=processed_vod.stream_id,
            vod_id=processed_vod.vod_id,
            clip_budget=processed_vod.clip_budget,
            candidate_count=candidate_count,
            selected=selected,
            selection_path=selection_path,
            candidate_path=candidate_path,
            status=status,
            error=error,
            retry_at=retry_at,
        )


def new_moments(
    moments: list[dict[str, Any]], listed: list[dict[str, Any]], limit: int
) -> list[dict[str, Any]]:
    """Up to ``limit`` of ``moments`` (best first) that no listed or taken moment covers."""
    taken: list[dict[str, Any]] = []
    for moment in moments:
        if len(taken) >= limit:
            break
        if all(_overlap_ratio(moment, other) <= MAX_CANDIDATE_OVERLAP for other in listed + taken):
            taken.append(moment)
    return taken


def tag_emotions(candidates: list[dict[str, Any]], emotions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each candidate with the emotion heard during it (``emotion``), for Gemini."""
    tagged = []
    for candidate in candidates:
        found = next(
            (
                moment["emotion"] for moment in emotions
                if candidate["start"] <= moment.get("onset", moment["start"]) <= candidate["end"] + 2
            ),
            None,
        )
        tagged.append({**candidate, "emotion": found} if found and "emotion" not in candidate else candidate)
    return tagged


def format_vod_highlight_selection(result: VODHighlightSelectionResult) -> str:
    if result.status == "error":
        return f"Erreur de selection Gemini pour {result.vod_id} : {result.error}"
    return (
        f"Selection Gemini {result.vod_id} : {len(result.selected)}/"
        f"{result.clip_budget} moments ({result.selection_path})"
    )