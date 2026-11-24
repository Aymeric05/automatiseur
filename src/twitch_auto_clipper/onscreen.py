"""Swear words written in the stream's own picture (game subtitles, chat overlay, alerts): blurred.

The app's own subtitles and hook are already masked with asterisks; this reads the rendered Short
(a frame every 0.5 s, RapidOCR on the CPU) and blurs each swear word (only the word) where it shows, for the
time it shows. A CaseOh GTA 6 Short with GTA's subtitles swearing got a YouTube warning (2026-11-23).
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path


SAMPLE_FPS = 2  # frames read per second of Short
READ_SCALE = 1.5  # frames read at 720x1280: ~0.4 s each, small chat text still read
HOLD_SECONDS = 0.6  # blurred this long before and after each sighting
PADDING = 6  # pixels around the word
_engine = []
# Read text often loses its spaces ("WHATTHEFUCK"): swear stems anywhere in the line, not whole
# words. A few false hits ("shitake") only blur a harmless line.
ONSCREEN_SWEARS = re.compile(
    r"f+u+c+k|sh[i1]t|b[i1]tch|cunt|n[i1]gg|f[a4]gg|wh[o0]re|slut|assh[o0]le|d[i1]ck|puss(?:y|ies)"
    r"|bastard|motherf|retard|c[o0]ck",
    re.IGNORECASE,
)


def _ocr():
    if not _engine:
        from rapidocr import RapidOCR

        _engine.append(RapidOCR())
    return _engine[0]


def _swear_spans(text: str) -> list[tuple[int, int]]:
    """Where swear words are in a read word: the stem stretched to its letters ("fucking", not "fuck")."""
    spans = []
    for match in ONSCREEN_SWEARS.finditer(text):
        left, right = match.start(), match.end()
        while right < len(text) and text[right].isalpha() and not ONSCREEN_SWEARS.match(text, right):
            right += 1
        spans.append((left, right))
    return spans


def profane_text_boxes(video: Path) -> list[tuple[float, float, int, int, int, int]]:
    """(from, to, x, y, w, h) of every text line with a swear word, in the Short's pixels."""
    found = []
    with tempfile.TemporaryDirectory() as directory:
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vf",
                        f"fps={SAMPLE_FPS},scale=iw/{READ_SCALE}:-2", str(Path(directory) / "f%05d.png")],
                       check=True, stdin=subprocess.DEVNULL, capture_output=True, timeout=600)
        frames = sorted(Path(directory).glob("f*.png"))
        if frames:
            from PIL import Image

            with Image.open(frames[0]) as first:
                width, height = int(first.width * READ_SCALE), int(first.height * READ_SCALE)
        for frame in frames:
            # Word boxes, so that only the swear word is blurred, never the rest of the line.
            result = _ocr()(str(frame), return_word_box=True)
            t = (int(frame.stem[1:]) - 1) / SAMPLE_FPS
            for line in result.word_results or ():
                for text, _score, box in line:
                    for left, right in _swear_spans(str(text)):
                        xs = [point[0] * READ_SCALE for point in box]
                        ys = [point[1] * READ_SCALE for point in box]
                        x0, x1 = min(xs), max(xs)
                        # Text read without its spaces ("WHATTHEFUCK"): only the swear word's share.
                        x0, x1 = x0 + (x1 - x0) * left / len(text), x0 + (x1 - x0) * right / len(text)
                        x, y = max(0, int(x0) - PADDING), max(0, int(min(ys)) - PADDING)
                        w, h = int(x1 - x0) + 2 * PADDING, int(max(ys) - min(ys)) + 2 * PADDING
                        w, h = min(w, width - x), min(h, height - y)  # never past the picture's edge
                        found.append((max(0.0, t - HOLD_SECONDS), t + HOLD_SECONDS, x, y, w - w % 2, h - h % 2))
    return found


def blur_profane_text(video: Path, encoder: tuple[str, ...]) -> int:
    """Blur the swear words shown in ``video`` (replaced in place); returns how many sightings."""
    boxes = profane_text_boxes(video)
    if not boxes:
        return 0
    graph = [f"[0:v]split={len(boxes) + 1}[v0]" + "".join(f"[s{i}]" for i in range(len(boxes)))]
    previous = "v0"
    for i, (start, end, x, y, w, h) in enumerate(boxes):
        graph.append(f"[s{i}]crop={w}:{h}:{x}:{y},gblur=sigma=30[b{i}]")
        graph.append(f"[{previous}][b{i}]overlay={x}:{y}:enable='between(t,{start:.2f},{end:.2f})'[o{i}]")
        previous = f"o{i}"
    blurred = video.with_name(f"{video.stem}.blur{video.suffix}")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-filter_complex", ";".join(graph),
                    "-map", f"[{previous}]", "-map", "0:a?", *encoder, "-c:a", "copy", str(blurred)],
                   check=True, stdin=subprocess.DEVNULL, capture_output=True, timeout=1800)
    blurred.replace(video)
    return len(boxes)
