"""Subtitle generation from word-level transcription timestamps."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class SubtitleGenerationError(RuntimeError):
    """Raised when word timestamps cannot be converted to subtitles."""


def _ass_time(seconds: float) -> str:
    total_cs = max(0, round(seconds * 100))
    hours, remainder = divmod(total_cs, 360000)
    minutes, remainder = divmod(remainder, 6000)
    whole_seconds, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{centiseconds:02d}"


def _escape_ass_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", " ")


def _words_from_segments(
    segments: list[dict[str, Any]], clip_start: float, clip_end: float
) -> list[dict[str, Any]]:
    words: list[dict[str, Any]] = []
    for segment in segments:
        for word in segment.get("words", []) or []:
            try:
                start = float(word["start"])
                end = float(word["end"])
                text = str(word["word"]).strip()
            except (KeyError, TypeError, ValueError) as error:
                raise SubtitleGenerationError("Mot horodate invalide dans la transcription.") from error
            if text and end > clip_start and start < clip_end:
                words.append(
                    {
                        "start": max(clip_start, start) - clip_start,
                        "end": min(clip_end, end) - clip_start,
                        "text": text,
                    }
                )
    return words


def generate_ass_subtitles(
    segments: list[dict[str, Any]],
    output_path: Path,
    clip_start: float = 0.0,
    clip_end: float | None = None,
    max_words: int = 4,
) -> Path:
    """Write readable ASS subtitle groups using real word timestamps."""
    if clip_start < 0 or (clip_end is not None and clip_end <= clip_start):
        raise SubtitleGenerationError("Les bornes du clip sont invalides.")
    if max_words < 1:
        raise SubtitleGenerationError("Le nombre maximal de mots doit etre positif.")

    if clip_end is None:
        clip_end = float("inf")
    words = _words_from_segments(segments, clip_start, clip_end)
    events: list[str] = []
    for index in range(0, len(words), max_words):
        group = words[index : index + max_words]
        start = group[0]["start"]
        end = max(start + 0.05, group[-1]["end"])
        text = " ".join(_escape_ass_text(word["text"]) for word in group)
        events.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{text}"
        )

    content = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,72,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,3,1,2,80,80,180,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(events) + ("\n" if events else "")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8-sig")
    return output_path
