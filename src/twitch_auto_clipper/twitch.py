"""Twitch VOD acquisition helpers."""

from pathlib import Path
from urllib.parse import urlparse


class TwitchDownloadError(RuntimeError):
    """Raised when a Twitch VOD cannot be downloaded."""


def is_twitch_vod_url(value: str) -> bool:
    """Return whether value is an HTTPS Twitch VOD URL."""
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    path_parts = [part for part in parsed.path.split("/") if part]
    return (
        parsed.scheme == "https"
        and host in {"twitch.tv", "www.twitch.tv", "m.twitch.tv"}
        and len(path_parts) == 2
        and path_parts[0].lower() == "videos"
        and path_parts[1].isdigit()
    )


def _get_youtube_dl():
    from yt_dlp import YoutubeDL

    return YoutubeDL


def download_twitch_vod(
    url: str,
    output_dir: Path,
    max_seconds: float | None = None,
    max_height: int | None = None,
) -> Path:
    """Download a Twitch VOD and return its local path (``<vod_id>.mp4``).

    ``max_seconds`` keeps only the beginning of the VOD and ``max_height``
    caps the resolution; both exist to keep test downloads small.
    """
    if not is_twitch_vod_url(url):
        raise ValueError("L'URL doit etre une URL HTTPS de VOD Twitch valide.")

    output_dir.mkdir(parents=True, exist_ok=True)
    vod_id = urlparse(url).path.rstrip("/").split("/")[-1]
    video_format = "bestvideo*+bestaudio/best"
    if max_height:
        video_format = f"bestvideo*[height<={max_height}]+bestaudio/best[height<={max_height}]"
    options = {
        # Named after the numeric VOD id (yt-dlp's own id is "v<id>"), which is
        # the name the acquisition manager looks for.
        "outtmpl": str(output_dir / f"{vod_id}.%(ext)s"),
        "format": video_format,
        "merge_output_format": "mp4",
        "noplaylist": True,
    }

    try:
        youtube_dl = _get_youtube_dl()
        if max_seconds:
            from yt_dlp.utils import download_range_func

            options["download_ranges"] = download_range_func([], [(0, max_seconds)])
        with youtube_dl(options) as downloader:
            info = downloader.extract_info(url, download=True)
            downloaded_path = Path(downloader.prepare_filename(info))
    except ModuleNotFoundError as error:
        raise TwitchDownloadError(
            "yt-dlp est requis pour telecharger une VOD Twitch."
        ) from error
    except Exception as error:
        raise TwitchDownloadError(f"Echec du telechargement Twitch : {error}") from error

    if downloaded_path.suffix.lower() != ".mp4":
        merged_path = downloaded_path.with_suffix(".mp4")
        if merged_path.is_file():
            downloaded_path = merged_path

    if not downloaded_path.is_file():
        raise TwitchDownloadError(
            f"Le telechargement est termine mais le fichier est introuvable : "
            f"{downloaded_path}"
        )

    return downloaded_path
