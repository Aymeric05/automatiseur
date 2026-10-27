"""Screen-record scripts/tiktok_demo.cmd for TikTok's app review (Windows).

The demo window is kept on top, along the bottom of the screen, so the
browser's TikTok pages stay visible above it. The recording stops cleanly a few
seconds after the demo ends, then is compressed under TikTok's 50 MB limit.
Usage: python scripts/record_tiktok_demo.py VIDEO_TO_SEND OUTPUT.mp4
"""

import ctypes
from pathlib import Path
import subprocess
import sys
import time

TITLE = "Automatiseur - TikTok integration demo"
ROOT = Path(__file__).resolve().parents[1]


def pin_bottom(user32) -> None:
    """Keep the demo window on top, on the bottom third of the screen."""
    width, height = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    for _ in range(100):
        window = user32.FindWindowW(None, TITLE)
        if window:
            user32.SetWindowPos(window, -1, 0, height * 2 // 3, width, height // 3 - 40, 0x0040)  # HWND_TOPMOST
            return
        time.sleep(0.1)


def main(video: str, output: Path) -> None:
    raw = output.with_suffix(".raw.mkv")
    recorder = subprocess.Popen(
        ["ffmpeg", "-y", "-f", "gdigrab", "-framerate", "20", "-i", "desktop",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", "-pix_fmt", "yuv420p", str(raw)],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(2)
    # conhost: a classic console window (Windows Terminal would ignore the pinning).
    demo = subprocess.Popen(["conhost.exe", "cmd.exe", "/c", str(ROOT / "scripts" / "tiktok_demo.cmd"), video],
                            cwd=ROOT, creationflags=subprocess.CREATE_NEW_CONSOLE)
    pin_bottom(ctypes.windll.user32)
    demo.wait()
    time.sleep(2)
    recorder.communicate(b"q", timeout=60)  # FFmpeg's own stop: the file is closed properly
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "2", "-i", str(raw), "-vf", "scale=1600:-2",
                    "-c:v", "libx264", "-preset", "slow", "-crf", "26", "-movflags", "+faststart", str(output)],
                   check=True)
    raw.unlink()
    print(f"{output} ({output.stat().st_size // 1024 // 1024} MB)")


if __name__ == "__main__":
    main(sys.argv[1], Path(sys.argv[2]))
