"""Twitch chat replay acquisition helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path
from urllib.parse import urlparse


class TwitchChatDownloadError(RuntimeError):
    """Raised when a Twitch chat replay cannot be downloaded."""


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


def download_twitch_chat(url: str, output_path: Path) -> Path:
    """Download a Twitch VOD chat replay as JSON."""
    vod_id = get_twitch_vod_id(url)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "TwitchDownloaderCLI",
        "chatdownload",
        "-u",
        vod_id,
        "-o",
        str(output_path),
    ]

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
