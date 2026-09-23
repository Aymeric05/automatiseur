"""Chat activity analysis helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ChatActivityError(RuntimeError):
    """Raised when Twitch chat data cannot be read."""


def load_chat_messages(input_path: Path) -> list[dict[str, Any]]:
    """Load timestamped messages from TwitchDownloaderCLI JSON output."""
    try:
        data = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ChatActivityError(f"Impossible de lire le chat : {input_path}") from error

    if isinstance(data, dict):
        messages = data.get("comments", [])
    else:
        messages = data
    if not isinstance(messages, list):
        raise ChatActivityError("Le fichier chat doit contenir une liste de messages.")

    normalized: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        try:
            timestamp = float(message["content_offset_seconds"])
        except (KeyError, TypeError, ValueError):
            continue
        normalized.append({"timestamp": timestamp, "message": message})
    return normalized


def count_messages_in_window(
    messages: list[dict[str, Any]], timestamp: float, window_seconds: float = 30.0
) -> int:
    """Count chat messages around a timestamp."""
    if window_seconds < 0:
        raise ValueError("La fenetre du chat doit etre positive ou nulle.")
    return sum(
        1
        for message in messages
        if abs(float(message["timestamp"]) - timestamp) <= window_seconds
    )


def add_chat_activity(
    candidates: list[dict[str, float]],
    messages: list[dict[str, Any]],
    window_seconds: float = 30.0,
) -> list[dict[str, float | int]]:
    """Add an explainable chat message count to highlight candidates."""
    return [
        {
            **candidate,
            "chat_messages": count_messages_in_window(
                messages, candidate["start"], window_seconds
            ),
        }
        for candidate in candidates
    ]


def _message_text(message: dict[str, Any]) -> str:
    payload = message.get("message", message)
    if not isinstance(payload, dict):
        return str(payload).strip()
    if payload.get("body"):
        return str(payload["body"]).strip()
    fragments = payload.get("fragments")
    if isinstance(fragments, list):
        return "".join(
            str(fragment.get("text", ""))
            for fragment in fragments
            if isinstance(fragment, dict)
        ).strip()
    return ""


def add_chat_messages(
    candidates: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    window_seconds: float = 30.0,
) -> list[dict[str, Any]]:
    """Attach timestamped chat messages to each candidate's time window."""
    if window_seconds < 0:
        raise ValueError("La fenetre du chat doit etre positive ou nulle.")
    enriched: list[dict[str, Any]] = []
    for candidate in candidates:
        start = float(candidate["start"])
        end = float(candidate["end"])
        matching_messages = [
            {
                "timestamp": float(message["timestamp"]),
                "text": _message_text(message),
            }
            for message in messages
            if start - window_seconds
            <= float(message["timestamp"])
            <= end + window_seconds
        ]
        enriched.append(
            {
                **candidate,
                "chat_messages": len(matching_messages),
                "chat_message_details": matching_messages,
            }
        )
    return enriched


def save_chat_activity(
    candidates: list[dict[str, float | int]], output_path: Path
) -> None:
    """Save candidates enriched with chat activity as JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
