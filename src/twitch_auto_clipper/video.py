"""FFmpeg helpers for creating vertical clips."""

from pathlib import Path
import re
import subprocess

from .framing import build_vertical_filter
from .subtitles import FONTS_DIR


def audio_levels(input_path: Path, start: float, seconds: int) -> list[float]:
    """Loudness (RMS, dB) of each second of ``input_path`` from ``start``; silence is -90."""
    result = subprocess.run(
        [
            "ffmpeg", "-v", "info", "-ss", str(max(0.0, start)), "-t", str(seconds),
            "-i", str(input_path), "-vn",
            "-af", "aresample=8000,asetnsamples=n=8000,astats=metadata=1:reset=1,"
                   "ametadata=print:key=lavfi.astats.Overall.RMS_level",
            "-f", "null", "-",
        ],
        capture_output=True, text=True, timeout=120, check=True,
    )
    return parse_audio_levels(result.stderr)


def parse_audio_levels(ffmpeg_output: str) -> list[float]:
    levels = []
    for value in re.findall(r"RMS_level=(\S+)", ffmpeg_output):
        try:
            levels.append(max(-90.0, float(value)))
        except ValueError:  # "-inf": silence
            levels.append(-90.0)
    return levels


def get_video_duration(input_path: Path) -> float:
    """Return the source duration reported by FFprobe."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(input_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return float(result.stdout.strip())


def validate_clip_times(start: float, end: float) -> None:
    """Raise ValueError when the requested interval is invalid."""
    if start < 0:
        raise ValueError("Le debut doit etre positif ou nul.")
    if end <= start:
        raise ValueError("La fin doit etre superieure au debut.")


def build_ffmpeg_command(
    input_path: Path,
    output_path: Path,
    start: float,
    end: float,
    subtitles_path: Path | None = None,
) -> list[str]:
    """Build the FFmpeg command for a central 9:16 crop."""
    validate_clip_times(start, end)
    duration = end - start
    vertical_filter = build_vertical_filter(input_path)
    if subtitles_path is not None:
        subtitle_file = str(subtitles_path.resolve()).replace("\\", "/").replace(":", "\\:")
        fonts_dir = str(FONTS_DIR).replace("\\", "/").replace(":", "\\:")
        vertical_filter += f",subtitles='{subtitle_file}':fontsdir='{fonts_dir}'"
    return [
        "ffmpeg",
        "-y",
        "-ss",
        str(start),
        "-i",
        str(input_path),
        "-t",
        str(duration),
        "-vf",
        vertical_filter,
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(output_path),
    ]


def create_vertical_clip(
    input_path: Path,
    output_path: Path,
    start: float,
    end: float,
    subtitles_path: Path | None = None,
) -> None:
    """Create a vertical clip by running FFmpeg."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = build_ffmpeg_command(
        input_path, output_path, start, end, subtitles_path=subtitles_path
    )
    subprocess.run(command, check=True)