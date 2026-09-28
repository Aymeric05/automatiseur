"""Twitch chat replay acquisition helpers."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse


class TwitchChatDownloadError(RuntimeError):
    """Raised when a Twitch chat replay cannot be downloaded."""


# Project-local copy (not on PATH): <repo>/tools/TwitchDownloaderCLI/TwitchDownloaderCLI.exe
LOCAL_CLI = Path(__file__).resolve().parents[2] / "tools" / "TwitchDownloaderCLI" / "TwitchDownloaderCLI.exe"


def find_twitch_downloader_cli() -> str | None:
    """Return the TwitchDownloaderCLI to run: the tools/ copy first, then PATH."""
    if LOCAL_CLI.is_file():
        return str(LOCAL_CLI)
    return shutil.which("TwitchDownloaderCLI")


def get_twitch_vod_id(url: str) -> str:
    """Extract the numeric VOD ID from a Twitch VOD URL."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path_parts = [part for part in parsed.path.split("/") if part]
    if (
        parsed.scheme != "https"
        or host not in {"twitch.tv", "www.twitch.tv", "m.twitch.tv"}
        or len(path_parts) != 2
        or path_parts[0].lower() != "videos"
        or not path_parts[1].isdigit()
    ):
        raise ValueError("L'URL doit etre une URL HTTPS de VOD Twitch valide.")
    return path_parts[1]


def download_twitch_chat(
    url: str,
    output_path: Path,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
) -> Path:
    """Download a Twitch VOD chat replay as JSON.

    ``start_seconds``/``end_seconds`` trim the replay (TwitchDownloaderCLI
    ``-b``/``-e``, passed in milliseconds). Message offsets stay absolute
    VOD seconds either way.
    """
    vod_id = get_twitch_vod_id(url)
    if start_seconds is not None and start_seconds < 0:
        raise ValueError("Le debut du chat doit etre positif ou nul.")
    if end_seconds is not None and end_seconds <= (start_seconds or 0):
        raise ValueError("La fin du chat doit etre superieure au debut.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        find_twitch_downloader_cli() or "TwitchDownloaderCLI",
        "chatdownload",
        "-u",
        vod_id,
    ]
    if start_seconds:
        command += ["-b", f"{round(start_seconds * 1000)}ms"]
    if end_seconds is not None:
        command += ["-e", f"{round(end_seconds * 1000)}ms"]
    command += ["-o", str(output_path)]

    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as error:
        raise TwitchChatDownloadError(
            "TwitchDownloaderCLI est introuvable dans le PATH."
        ) from error
    except subprocess.CalledProcessError as error:
        raise TwitchChatDownloadError(
            f"Echec du telechargement du chat Twitch (code {error.returncode})."
        ) from error

    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise TwitchChatDownloadError(
            f"Le telechargement est termine mais le fichier chat est vide : {output_path}"
        )
    return output_path
