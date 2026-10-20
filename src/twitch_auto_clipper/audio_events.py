"""Laughter, screams and gasps in a VOD's audio, found by the YAMNet sound classifier.

They catch reactions the transcript misses: a laughing fit transcribes as
"I'm like I'm like", a shocked scream as nothing at all.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any

# YAMNet (AudioSet, 521 classes) in ONNX, 16 MB, Apache-2.0; kept in the Hugging Face cache.
YAMNET_REPO = "audiomagic/yamnet-onnx"
SAMPLE_RATE = 16000
FRAME_HOP_SECONDS = 0.48  # one score frame every 0.48 s, each covering 0.96 s
CHUNK_SECONDS = 600  # audio decoded and scored 10 minutes at a time (bounded memory)
# Indices in yamnet_class_map.csv of the sounds of a strong reaction.
EMOTIONS = {
    "laughter": (13, 14, 15, 16, 17, 18),  # Laughter, Baby laughter, Giggle, Snicker, Belly laugh, Chuckle
    "scream": (6, 7, 9, 10, 11),  # Shout, Bellow, Yell, Children shouting, Screaming
    "gasp": (39,),
    "crying": (19, 21, 22),  # Crying/sobbing, Whimper, Wail/moan
    "cheering": (8, 61, 62),  # Whoop, Cheering, Applause
}
# A frame counts above this score: ordinary speech stays below 0.02 (99th percentile).
EVENT_THRESHOLD = 0.1
EVENT_GAP_SECONDS = 2.0  # frames closer than this belong to the same reaction
MAX_EVENT_SECONDS = 20.0  # a longer one (a noisy game) is split
BEFORE_SECONDS = 15.0  # what triggers the reaction comes just before it
AFTER_SECONDS = 5.0
MAX_EVENTS = 100


def detect_emotions(audio_path: Path, limit: int = MAX_EVENTS) -> list[dict[str, Any]]:
    """Reaction moments of ``audio_path``, strongest first (``"source": "emotion"``)."""
    import numpy as np
    import onnxruntime
    from huggingface_hub import hf_hub_download

    session = onnxruntime.InferenceSession(
        hf_hub_download(YAMNET_REPO, "yamnet.onnx"), providers=["CPUExecutionProvider"]
    )
    labels = list(EMOTIONS)
    frames: list[tuple[float, str, float]] = []
    process = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(audio_path), "-vn", "-ac", "1",
         "-ar", str(SAMPLE_RATE), "-f", "f32le", "-"],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    offset = 0.0
    try:
        while chunk := process.stdout.read(CHUNK_SECONDS * SAMPLE_RATE * 4):
            wave = np.frombuffer(chunk[: len(chunk) // 4 * 4], dtype=np.float32)
            if len(wave) >= SAMPLE_RATE:  # the model needs at least one 0.96 s frame
                scores = session.run(["output_0"], {"waveform": wave})[0]
                groups = np.stack([scores[:, list(EMOTIONS[label])].max(axis=1) for label in labels], axis=1)
                for index in np.flatnonzero(groups.max(axis=1) >= EVENT_THRESHOLD):
                    best = int(groups[index].argmax())
                    frames.append((
                        float(offset + index * FRAME_HOP_SECONDS), labels[best], float(groups[index, best])
                    ))
            offset += len(wave) / SAMPLE_RATE
        process.wait()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    if process.returncode != 0:
        raise RuntimeError(f"FFmpeg n'a pas pu lire l'audio (code {process.returncode}).")
    return emotion_moments(frames)[:limit]


def emotion_moments(frames: list[tuple[float, str, float]]) -> list[dict[str, Any]]:
    """Group scored frames ``(time, emotion, score)`` into reaction moments, strongest first.

    A reaction's strength is the sum of its frames' scores: a long laughing
    fit beats a single loud frame.
    """
    events: list[dict[str, Any]] = []
    for time, label, score in sorted(frames):
        last = events[-1] if events else None
        if last and time - last["last"] <= EVENT_GAP_SECONDS and time - last["onset"] <= MAX_EVENT_SECONDS:
            last["last"] = time
            last["scores"][label] = last["scores"].get(label, 0.0) + score
        else:
            events.append({"onset": time, "last": time, "scores": {label: score}})
    moments = [
        {
            "start": round(max(0.0, event["onset"] - BEFORE_SECONDS), 2),
            "onset": round(event["onset"], 2),  # when the reaction is heard
            "end": round(event["last"] + 2 * FRAME_HOP_SECONDS + AFTER_SECONDS, 2),
            "score": round(sum(event["scores"].values()), 2),
            "source": "emotion",
            "emotion": max(event["scores"], key=event["scores"].get),
        }
        for event in events
    ]
    moments.sort(key=lambda moment: -moment["score"])
    return moments
