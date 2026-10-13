"""Optional Gemini evaluation of detected highlight candidates."""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import time
from typing import Any

from .daily_quota import DailyQuota


CONTEXT_SECONDS = 15.0  # transcript shared with Gemini before and after each candidate
GEMINI_TIMEOUT_MS = 300_000
# "503 UNAVAILABLE: high demand" spikes are short: retry once before failing
# (every attempt counts against the daily request quota).
TRANSIENT_RETRY_DELAYS = (30.0,)
TRANSIENT_MARKERS = ("503", "500", "unavailable", "internal", "deadline", "high demand")


class GeminiEvaluationError(RuntimeError):
    """Raised when Gemini cannot evaluate highlight candidates."""

    def __init__(self, message: str, retry_at: datetime | None = None) -> None:
        super().__init__(message)
        self.retry_at = retry_at  # set when only the daily quota is missing


QUOTA_ERROR_MARKERS = ("429", "resource_exhausted", "exceeded your current quota")


EVALUATION_RESPONSE_FORMAT = {
    "type": "text",
    "mime_type": "application/json",
    "schema": {
        "type": "object",
        "properties": {
            "evaluations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "candidate_id": {"type": "string"},
                        "interesting": {"type": "boolean"},
                        "score": {"type": "number", "minimum": 0, "maximum": 100},
                        "justification": {"type": "string"},
                    },
                    "required": [
                        "candidate_id",
                        "interesting",
                        "score",
                        "justification",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["evaluations"],
        "additionalProperties": False,
    },
}


def _get_gemini_client():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise GeminiEvaluationError("La variable GEMINI_API_KEY est requise.")

    try:
        from google import genai
    except ModuleNotFoundError as error:
        raise GeminiEvaluationError(
            "Le paquet google-genai est requis pour utiliser Gemini."
        ) from error

    # A stalled request must not freeze the VOD worker (timeout in milliseconds).
    return genai.Client(api_key=api_key, http_options={"timeout": GEMINI_TIMEOUT_MS})


def _candidate_context(
    candidates: list[dict[str, Any]], transcription: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    def spoken(from_time: float, to_time: float) -> str:
        return " ".join(
            str(segment.get("text", "")).strip()
            for segment in transcription
            if float(segment.get("end", 0)) > from_time
            and float(segment.get("start", 0)) < to_time
        ).strip()

    context: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates, start=1):
        start = float(candidate["start"])
        end = float(candidate["end"])
        signal = candidate.get("chat_signal")
        context.append(
            {
                "candidate_id": f"candidate_{index}",
                "start": start,
                "end": end,
                "duration": round(end - start, 1),
                "heuristic_score": candidate.get("score", 0),
                # Compact chat summary, never the raw messages (hundreds per candidate).
                "chat": {key: value for key, value in signal.items() if key != "rate"}
                if isinstance(signal, dict)
                else None,
                "transcript": spoken(start, end),
                # What is said just around the clip, to judge if it stands alone.
                "context_before": spoken(start - CONTEXT_SECONDS, start),
                "context_after": spoken(end, end + CONTEXT_SECONDS),
            }
        )
    return context


def _build_prompt(
    context: list[dict[str, Any]],
    selection_count: int | None = None,
) -> str:
    prompt = (
        "Evalue les candidats suivants pour un Short Twitch. "
        "Classe-les selon leur potentiel d'interet pour un public court. "
        "Utilise d'abord la transcription, puis le score heuristique et le resume du chat. "
        "chat (null si indisponible) resume les reactions du chat juste apres le clip : "
        "messages, distinct_authors, activity_ratio (activite par rapport aux minutes voisines), "
        "laugh_ratio, short_reaction_ratio, top_reactions (messages courts repetes, codes "
        "propres a la chaine possibles) et sample_messages (quelques messages). "
        "Le chat est un contexte secondaire, pas une preuve : une reaction peut viser un "
        "evenement visuel absent de la transcription. Si reliable est false (debut de stream, "
        "salutations, pas de reference), ne t'appuie pas sur le chat. "
        "Retourne uniquement un JSON valide sous la forme "
        '{"evaluations":[{"candidate_id":"candidate_1",'
        '"interesting":true,"score":0,"justification":"..."}]} . '
        "Le score Gemini doit etre entre 0 et 100. "
        "La justification doit etre courte et concrete. "
        "transcript est le texte du clip ; context_before et context_after sont ce qui "
        "est dit juste avant et apres : juge si le clip se comprend seul et forme un "
        "moment complet. Base-toi sur le contenu reel, pas seulement sur le score heuristique. "
        "Conserve exactement les candidate_id fournis.\n\n"
        + json.dumps(context, ensure_ascii=False)
    )
    if selection_count is not None:
        prompt += (
            f"\nSelectionne exactement {selection_count} candidats distincts, "
            "en priorisant les moments genuinement interessants selon le contenu, "
            "les reactions du streamer, l'activite du chat et le score heuristique. "
            "Si le nombre de candidats fournis est inferieur, retourne-les tous. "
            "Mets interesting a false pour tout candidat qui ne ferait pas un Short "
            "interessant : il ne sera ni genere ni publie. Si aucun moment de la VOD "
            "ne merite un Short, mets interesting a false partout. "
            "N'invente aucun moment ni aucun candidate_id."
        )
    return prompt


def _parse_response(response_text: str, candidate_ids: set[str]) -> list[dict[str, Any]]:
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as error:
        raise GeminiEvaluationError("Gemini a retourne un JSON invalide.") from error

    evaluations = data.get("evaluations") if isinstance(data, dict) else None
    if not isinstance(evaluations, list):
        raise GeminiEvaluationError("La reponse Gemini ne contient pas evaluations.")

    validated: list[dict[str, Any]] = []
    for evaluation in evaluations:
        if not isinstance(evaluation, dict):
            raise GeminiEvaluationError("Une evaluation Gemini est invalide.")
        candidate_id = evaluation.get("candidate_id")
        justification = evaluation.get("justification")
        score = evaluation.get("score")
        interesting = evaluation.get("interesting")
        if (
            candidate_id not in candidate_ids
            or not isinstance(justification, str)
            or not justification.strip()
            or not isinstance(score, (int, float))
            or not 0 <= score <= 100
            or not isinstance(interesting, bool)
        ):
            raise GeminiEvaluationError("Une evaluation Gemini ne respecte pas le format attendu.")
        validated.append(
            {
                "candidate_id": candidate_id,
                "interesting": interesting,
                "score": score,
                "justification": justification.strip(),
            }
        )
    return validated


def evaluate_candidates(
    candidates: list[dict[str, Any]],
    transcription: list[dict[str, Any]],
    model: str = "gemini-3.6-flash",
    selection_count: int | None = None,
    quota: DailyQuota | None = None,
) -> list[dict[str, Any]]:
    """Ask Gemini to evaluate candidates using transcript and optional chat counts.

    With ``quota``, every request (retries included) is counted and none is
    sent once the daily limit is reached.
    """
    context = _candidate_context(candidates, transcription)
    if selection_count is not None:
        if selection_count < 0:
            raise GeminiEvaluationError("Le nombre de selections ne peut pas etre negatif.")
        if selection_count == 0 or not context:
            return []
        expected_count = min(selection_count, len(context))
    else:
        expected_count = None

    client = _get_gemini_client()
    prompt = _build_prompt(context, selection_count=expected_count)
    for delay in (*TRANSIENT_RETRY_DELAYS, None):
        if quota is not None:
            if not quota.available():
                raise GeminiEvaluationError(
                    f"Quota Gemini du jour atteint ({quota.daily_limit} requetes).",
                    retry_at=quota.next_reset(),
                )
            quota.record_use()
        try:
            # generate_content, not the beta Interactions API: the latter has its own,
            # much smaller quota and answered HTTP 429 while generate_content worked.
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config={
                    "response_mime_type": EVALUATION_RESPONSE_FORMAT["mime_type"],
                    "response_json_schema": EVALUATION_RESPONSE_FORMAT["schema"],
                    "automatic_function_calling": {"disable": True},  # no tools: no AFC warning
                },
            )
            break
        except Exception as error:
            if quota is not None and any(marker in str(error).lower() for marker in QUOTA_ERROR_MARKERS):
                quota.mark_exhausted()  # Google refused: no more requests today
                raise GeminiEvaluationError(
                    f"Echec de l'appel Gemini : {error}", retry_at=quota.next_reset()
                ) from error
            if delay is None or not any(marker in str(error).lower() for marker in TRANSIENT_MARKERS):
                raise GeminiEvaluationError(f"Echec de l'appel Gemini : {error}") from error
            time.sleep(delay)

    response_text = getattr(response, "text", None)
    if not isinstance(response_text, str) or not response_text.strip():
        raise GeminiEvaluationError("Gemini a retourne une reponse vide.")
    evaluations = _parse_response(
        response_text,
        {item["candidate_id"] for item in context},
    )
    if expected_count is not None:
        candidate_ids = [evaluation["candidate_id"] for evaluation in evaluations]
        if len(evaluations) != expected_count or len(set(candidate_ids)) != expected_count:
            raise GeminiEvaluationError(
                f"Gemini doit retourner exactement {expected_count} candidats distincts."
            )
        evaluations.sort(key=lambda evaluation: evaluation["score"], reverse=True)
    return evaluations


def select_candidates(
    candidates: list[dict[str, Any]],
    transcription: list[dict[str, Any]],
    requested_count: int,
    model: str = "gemini-3.6-flash",
    quota: DailyQuota | None = None,
) -> list[dict[str, Any]]:
    """Return an exact, distinct Gemini selection, or every candidate if fewer exist."""
    if requested_count < 0:
        raise GeminiEvaluationError("Le nombre de selections ne peut pas etre negatif.")
    if requested_count == 0 or not candidates:
        return []
    return evaluate_candidates(
        candidates,
        transcription,
        model=model,
        selection_count=requested_count,
        quota=quota,
    )


def select_candidate(
    candidates: list[dict[str, Any]],
    transcription: list[dict[str, Any]],
    model: str = "gemini-3.6-flash",
) -> tuple[int, dict[str, Any]]:
    """Select the highest-ranked valid Gemini evaluation."""
    if not candidates:
        raise GeminiEvaluationError("Aucun candidat disponible pour Gemini.")

    evaluations = evaluate_candidates(candidates, transcription, model=model)
    if not evaluations:
        raise GeminiEvaluationError("Gemini n'a selectionne aucun candidat.")
    selected = max(evaluations, key=lambda evaluation: evaluation["score"])
    candidate_id = selected["candidate_id"]
    try:
        candidate_index = int(candidate_id.removeprefix("candidate_")) - 1
    except (AttributeError, ValueError) as error:
        raise GeminiEvaluationError(
            f"Identifiant de candidat Gemini invalide : {candidate_id}"
        ) from error
    if candidate_index < 0 or candidate_index >= len(candidates):
        raise GeminiEvaluationError(
            f"Candidat Gemini inexistant : {candidate_id}"
        )
    return candidate_index, selected


def load_json(input_path: Path, label: str) -> Any:
    """Load a UTF-8 JSON file for Gemini evaluation."""
    try:
        return json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GeminiEvaluationError(f"Impossible de lire {label} : {input_path}") from error


def save_evaluations(evaluations: list[dict[str, Any]], output_path: Path) -> None:
    """Save Gemini evaluations as UTF-8 JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(evaluations, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
