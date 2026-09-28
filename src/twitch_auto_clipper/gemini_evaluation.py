"""Optional Gemini evaluation of detected highlight candidates."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


CONTEXT_SECONDS = 15.0  # transcript shared with Gemini before and after each candidate


class GeminiEvaluationError(RuntimeError):
    """Raised when Gemini cannot evaluate highlight candidates."""


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

    return genai.Client(api_key=api_key)


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
) -> list[dict[str, Any]]:
    """Ask Gemini to evaluate candidates using transcript and optional chat counts."""
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
    try:
        interaction = client.interactions.create(
            model=model,
            input=_build_prompt(context, selection_count=expected_count),
            response_format=EVALUATION_RESPONSE_FORMAT,
        )
    except Exception as error:
        raise GeminiEvaluationError(f"Echec de l'appel Gemini : {error}") from error

    response_text = getattr(interaction, "output_text", None)
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
