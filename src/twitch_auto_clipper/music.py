"""Background music in a Short: found, and removed when the moment is worth it.

A stream's music is rarely free: YouTube's Content ID blocks or claims the Short
(an Emiru Short was blocked in two countries for its music bed on 2026-11-02).
Demucs (on the GPU) splits a moment's sound into the voices and the rest; the
YAMNet classifier then looks for music in the whole sound and in the rest, where
no voice hides it. Measured on a labeled set (real speech with real stream music
added, 2026-11-06): no false alarm on 5 voices nor on 10 real talking Shorts;
instrumental music found 12/12 from -18 dB under the voice, a loud song 2/2;
quiet music (-24/-30 dB) only 3/9 and quiet songs 0/2.

Removing it (keeping Demucs' voices only) lowers very loud instrumental music by 13
to 24 dB, but quieter music by as little as 4 dB, and never a song: only very loud
instrumental music under a good moment is removed, the rest is dropped (vod_pipeline).
"""

from __future__ import annotations

from pathlib import Path
import subprocess
from threading import Lock
from typing import Any

import numpy as np

from .audio_events import MUSIC_CLASSES, SAMPLE_RATE, YAMNET_REPO

# One GPU job at a time: Whisper and Demucs together would not fit in a 4 GB card.
GPU_LOCK = Lock()
RATE = 44100
REST_MUSIC_SCORE = 0.1
_models: dict[str, Any] = {}


def _demucs():
    if "demucs" not in _models:
        from demucs.pretrained import get_model
        import torch

        model = get_model("htdemucs").eval()
        _models["device"] = "cuda" if torch.cuda.is_available() else "cpu"
        _models["demucs"] = model.to(_models["device"])
    return _models["demucs"]


def _yamnet():
    if "yamnet" not in _models:
        import onnxruntime
        from huggingface_hub import hf_hub_download

        _models["yamnet"] = onnxruntime.InferenceSession(
            hf_hub_download(YAMNET_REPO, "yamnet.onnx"), providers=["CPUExecutionProvider"]
        )
    return _models["yamnet"]


def _load(path: Path, start: float = 0.0, seconds: float | None = None) -> np.ndarray:
    audio = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(start), *(["-t", str(seconds)] if seconds else []), "-i", str(path),
         "-vn", "-ac", "2", "-ar", str(RATE), "-f", "f32le", "-"],
        stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=300,
    ).stdout
    return np.frombuffer(audio[: len(audio) // 8 * 8], np.float32).reshape(-1, 2).T.copy()


def _split(sound: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The voices and the rest (music, effects, ambience)."""
    import torch
    from demucs.apply import apply_model

    model = _demucs()
    with GPU_LOCK, torch.no_grad():
        stems = apply_model(model, torch.from_numpy(sound)[None].to(_models["device"]), device=_models["device"],
                            progress=False)[0].cpu().numpy()
    vocals = stems[model.sources.index("vocals")]
    return vocals, stems.sum(axis=0) - vocals


def _music_share(sound: np.ndarray) -> float:
    mono = sound.mean(axis=0)
    wave = np.interp(np.arange(0, len(mono), RATE / SAMPLE_RATE), np.arange(len(mono)), mono).astype(np.float32)
    if len(wave) < SAMPLE_RATE:
        return 0.0
    scores = _yamnet().run(["output_0"], {"waveform": wave})[0]
    return float((scores[:, list(MUSIC_CLASSES)].max(axis=1) > REST_MUSIC_SCORE).mean())


def music_profile(audio_path: Path, start: float, end: float) -> dict[str, float]:
    """``whole``: share of the moment with music; ``rest``: the same once the voices are
    removed; ``rest_level``: loudness of the rest against the whole sound (dB)."""
    sound = _load(audio_path, start, end - start)
    _, rest = _split(sound)
    level = 10 * np.log10(float(np.mean(rest ** 2)) / (float(np.mean(sound ** 2)) + 1e-12) + 1e-12)
    return {"whole": _music_share(sound), "rest": _music_share(rest), "rest_level": float(level)}


def keep_voices_only(video: Path) -> bool:
    """Replace a rendered Short's sound by its voices (the music removed); False if it failed."""
    temporary = video.with_name(f"{video.stem}.voices.mp4")
    try:
        vocals, _ = _split(_load(video))
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(video), "-f", "f32le", "-ar", str(RATE), "-ac", "2", "-i", "-",
             "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
             "-movflags", "+faststart", str(temporary)],
            input=np.clip(vocals.T, -1, 1).astype(np.float32).tobytes(), capture_output=True,
            check=True, timeout=300,
        )
        temporary.replace(video)
        return True
    except Exception:
        temporary.unlink(missing_ok=True)
        return False
