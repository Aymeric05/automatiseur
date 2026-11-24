"""Swear words written in the picture are blurred (real FFmpeg and OCR on a small test video)."""

import subprocess
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("rapidocr")

from twitch_auto_clipper.onscreen import blur_profane_text, profane_text_boxes  # noqa: E402
from twitch_auto_clipper.vod_shorts import VIDEO_ENCODER  # noqa: E402

FONT = Path(__file__).resolve().parents[1] / "assets" / "fonts" / "Poppins-ExtraBold.ttf"


def test_a_swear_word_shown_in_the_stream_is_blurred_and_the_rest_left_readable():
    with tempfile.TemporaryDirectory() as directory:
        video = Path(directory) / "short.mp4"
        font = str(FONT).replace(chr(92), "/").replace(":", chr(92) + ":")
        subprocess.run([
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=1080x1920:d=3", "-vf",
            f"drawtext=fontfile='{font}':text='WHAT THE FUCK':fontsize=90:fontcolor=white:x=100:y=1500,"
            f"drawtext=fontfile='{font}':text='NICE SHOT':fontsize=90:fontcolor=white:x=100:y=300",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
        ], check=True)
        boxes = profane_text_boxes(video)
        assert boxes and all(1300 < box[3] < 1700 for box in boxes)  # only the swearing line
        assert blur_profane_text(video, VIDEO_ENCODER) > 0
        assert profane_text_boxes(video) == []  # no longer readable
        from twitch_auto_clipper.onscreen import _ocr

        frame = Path(directory) / "frame.png"
        subprocess.run(["ffmpeg", "-v", "error", "-ss", "1", "-i", str(video), "-frames:v", "1", str(frame)], check=True)
        read = " ".join(_ocr()(str(frame)).txts)
        assert "NICE" in read  # the rest of the picture kept
        assert "WHAT" in read and "THE" in read  # and the rest of the swearing line: only the word is blurred


def test_only_the_swear_word_of_a_word_read_without_spaces_is_blurred():
    from twitch_auto_clipper.onscreen import _swear_spans

    assert _swear_spans("WHATTHEFUCK") == [(7, 11)]
    assert _swear_spans("fucking") == [(0, 7)]  # the whole word, not just its stem
    assert _swear_spans("Gettin'") == []
