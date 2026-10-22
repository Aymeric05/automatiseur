"""Subtitle generation from word-level transcription timestamps."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from .profanity import PROFANITY

# libass override tags: the word is drawn heavily blurred (unreadable), then the style is restored.
BLURRED_WORD = r"{\bord0\shad0\blur18}%s{\r}"


# Gill Sans Ultra Bold (installed with Office), else Impact, else Arial Bold.
# Bangers (Google Fonts, SIL Open Font License), shipped with the app; Windows fonts as fallback.
HOOK_FONTS = (
    str(Path(__file__).resolve().parents[2] / "assets" / "fonts" / "Bangers-Regular.ttf"),
    "ARLRDBD.TTF", "arialbd.ttf",
)
HOOK_FONT_SIZE = 84  # Bangers is narrow: a bit bigger for the same presence
HOOK_COLOR = "white"  # black outline: readable on any background
HOOK_STROKE = 6
HOOK_DEPTH = 7  # pixels of 3D relief under the text
HOOK_MAX_TEXT_WIDTH = 960  # pixels, in the 1080px-wide Short


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


def _subtitle_word(word: str) -> str:
    """A subtitle word; a swear word is blurred (it is also muted in the audio)."""
    escaped = _escape_ass_text(word)
    return BLURRED_WORD % escaped if PROFANITY.search(word) else escaped


def _join_words(words: list[str]) -> str:
    # Whisper splits "4 p.m." into "p" + ".m.": punctuation sticks to the previous word.
    text = ""
    for word in words:
        text += word if text and word[0] in ",.!?;:'%" else f" {word}" if text else word
    return text


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


def _is_emoji(char: str) -> bool:
    # ponytail: code point ranges, not the full emoji list; enough for simple emojis.
    code = ord(char)
    return code >= 0x1F000 or 0x2600 <= code <= 0x27BF or 0x2B00 <= code <= 0x2BFF


def _runs(text: str) -> list[list[Any]]:
    """Split text into [chunk, is_emoji] runs, each drawn with its own font."""
    runs: list[list[Any]] = []
    for char in text:
        emoji = _is_emoji(char)
        if runs and runs[-1][1] == emoji:
            runs[-1][0] += char
        else:
            runs.append([char, emoji])
    return runs


def _simple_emojis(text: str) -> str:
    # Without a text shaping library, a joined emoji (runner + male sign) would show
    # as its parts and variation selectors as boxes: keep the base emoji only.
    return re.sub("\u200d.|[\ufe0f\U0001F3FB-\U0001F3FF]", "", text)


def render_hook_image(text: str, output_path: Path) -> Path:
    """Draw the hook as white text, without emojis, on a transparent PNG.

    A black outline, a 3D extrusion and a soft drop shadow keep it readable on
    any background. libass draws emojis as plain white outlines, hence an image
    overlay. Uses Windows fonts (the first available of ``HOOK_FONTS``, and
    Segoe UI Emoji).
    """
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont
    except ImportError as error:
        raise SubtitleGenerationError(f"Pillow indisponible : {error}") from error
    # Never an emoji on the video (they stay in the YouTube title and description).
    text = re.sub(r"\s+", " ", re.sub("[\U0001F000-\U0001FFFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D]", "", text)).strip()
    if not text:
        raise SubtitleGenerationError("Phrase d'accroche vide sans ses emojis.")
    text_font = None
    for name in HOOK_FONTS:
        try:
            text_font = ImageFont.truetype(name, HOOK_FONT_SIZE)
            break
        except OSError:
            continue
    try:
        emoji_font = ImageFont.truetype("seguiemj.ttf", round(HOOK_FONT_SIZE * 0.85))
    except OSError as error:
        raise SubtitleGenerationError(f"Police emoji indisponible : {error}") from error
    if text_font is None:
        raise SubtitleGenerationError(f"Aucune police disponible parmi {HOOK_FONTS}.")
    fonts = {False: text_font, True: emoji_font}

    words = _simple_emojis(text).split()
    if not words:
        raise SubtitleGenerationError("Phrase d'accroche vide.")

    def width(line: str) -> float:
        return sum(fonts[emoji].getlength(chunk) for chunk, emoji in _runs(line))

    lines: list[str] = []
    for word in words:
        if lines and width(f"{lines[-1]} {word}") <= HOOK_MAX_TEXT_WIDTH:
            lines[-1] = f"{lines[-1]} {word}"
        else:
            lines.append(word)
    ascent, descent = text_font.getmetrics()
    line_height = ascent + descent
    margin = HOOK_STROKE + HOOK_DEPTH + 20  # room for the outline, relief and shadow
    size = (
        round(max(width(line) for line in lines)) + 2 * margin,
        len(lines) * line_height + 2 * margin,
    )
    face = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(face)
    for index, line in enumerate(lines):
        x = (size[0] - width(line)) / 2
        baseline = margin + index * line_height + ascent
        for chunk, emoji in _runs(line):
            if emoji:
                draw.text((x, baseline), chunk, font=emoji_font, anchor="ls", embedded_color=True)
            else:
                draw.text((x, baseline), chunk, font=text_font, fill=HOOK_COLOR, anchor="ls",
                          stroke_width=HOOK_STROKE, stroke_fill="black")
            x += fonts[emoji].getlength(chunk)

    alpha = face.getchannel("A")
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    shadow = Image.new("RGBA", size, (0, 0, 0, 0))
    shadow.putalpha(alpha.filter(ImageFilter.GaussianBlur(10)).point(lambda a: a * 7 // 10))
    image.alpha_composite(shadow, dest=(0, HOOK_DEPTH + 6))
    relief = Image.new("RGBA", size, (0, 0, 0, 255))
    relief.putalpha(alpha)
    for depth in range(HOOK_DEPTH, 0, -1):  # the text's own shape, stacked downwards
        image.alpha_composite(relief, dest=(0, depth))
    image.alpha_composite(face)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    return output_path


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
        text = _join_words([_subtitle_word(word["text"]) for word in group])
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
