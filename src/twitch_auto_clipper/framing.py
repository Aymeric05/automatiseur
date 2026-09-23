"""CPU-friendly focus detection for vertical video framing."""

from __future__ import annotations

from pathlib import Path


def detect_horizontal_focus(input_path: Path, sample_count: int = 5) -> float | None:
    """Return a normalized face focus position, or None for centered fallback."""
    if sample_count < 1:
        return None
    try:
        import cv2
    except ImportError:
        return None

    capture = cv2.VideoCapture(str(input_path))
    try:
        if not capture.isOpened():
            return None
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        frame_width = float(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        if frame_count <= 0 or frame_width <= 0:
            return None

        detector = cv2.CascadeClassifier(
            str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml")
        )
        if detector.empty():
            return None

        positions: list[float] = []
        for frame_index in _sample_indices(frame_count, sample_count):
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = capture.read()
            if not ok:
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5)
            if len(faces) == 0:
                continue
            x, _, width, _ = max(faces, key=lambda face: face[2] * face[3])
            positions.append((x + width / 2) / frame_width)

        if not positions:
            return None
        return max(0.0, min(1.0, sum(positions) / len(positions)))
    except Exception:
        return None
    finally:
        capture.release()


def _sample_indices(frame_count: int, sample_count: int) -> list[int]:
    if sample_count == 1:
        return [frame_count // 2]
    last_index = max(0, frame_count - 1)
    return [round(last_index * index / (sample_count - 1)) for index in range(sample_count)]


def build_vertical_filter(input_path: Path) -> str:
    """Build a vertical filter using detected focus or the centered fallback."""
    focus = detect_horizontal_focus(input_path)
    if focus is None:
        return (
            "scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920"
        )

    return (
        "crop=ih*(9/16):ih:(iw-ih*(9/16))*"
        f"{focus:.4f}:0,scale=1080:1920"
    )
