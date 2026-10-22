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
    audio_only: bool = False,
    quiet: bool = False,
    rate_limit: int | None = None,
) -> Path:
    """Download a Twitch VOD and return its local path.

    The video is saved as ``<vod_id>.mp4``; with ``audio_only`` only the audio
    track is saved, as ``<vod_id>_audio.<ext>`` (~70 MB per hour instead of
    several GB): it is all the transcription needs, the Shorts then read their
    few seconds of video straight from Twitch. ``max_seconds`` keeps only the
    beginning of the VOD and ``max_height`` caps the resolution (test runs).
    ``rate_limit`` caps the download speed (bytes per second).
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
        "outtmpl": str(output_dir / f"{vod_id}{'_audio' if audio_only else ''}.%(ext)s"),
        # Twitch VODs have an audio-only rendition; the smallest video is the fallback.
        "format": "bestaudio/worst" if audio_only else video_format,
        "noplaylist": True,
        "quiet": quiet,
        "noprogress": quiet,
    }
    if not audio_only:
        options["merge_output_format"] = "mp4"
    if rate_limit:
        options["ratelimit"] = rate_limit  # leaves bandwidth for the rest of the home network

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

    if not audio_only and downloaded_path.suffix.lower() != ".mp4":
        merged_path = downloaded_path.with_suffix(".mp4")
        if merged_path.is_file():
            downloaded_path = merged_path

    if not downloaded_path.is_file():
        raise TwitchDownloadError(
            f"Le telechargement est termine mais le fichier est introuvable : "
            f"{downloaded_path}"
        )

    return downloaded_path


def resolve_twitch_video_url(url: str, max_height: int | None = None) -> str:
    """Return the HLS playlist URL of the VOD video (audio included).

    FFmpeg reads only the requested seconds from it, so a Short never needs
    the whole VOD on disk. The URL carries a short-lived Twitch token: resolve
    it right before use, never store it. Without ``max_height``, the best rendition
    Twitch has (the streamer's source quality, 1440p included).
    """
    if not is_twitch_vod_url(url):
        raise ValueError("L'URL doit etre une URL HTTPS de VOD Twitch valide.")
    options = {
        # Twitch renditions carry video and audio together: one URL is enough.
        "format": f"best[height<={max_height}]/best" if max_height else "best",
        "noplaylist": True,
        "quiet": True,
    }
    try:
        with _get_youtube_dl()(options) as downloader:
            info = downloader.extract_info(url, download=False)
    except ModuleNotFoundError as error:
        raise TwitchDownloadError("yt-dlp est requis pour lire une VOD Twitch.") from error
    except Exception as error:
        raise TwitchDownloadError(f"Flux video Twitch indisponible : {error}") from error
    stream_url = info.get("url") if isinstance(info, dict) else None
    if not stream_url:
        raise TwitchDownloadError("yt-dlp n'a renvoye aucune URL video pour cette VOD.")
    return stream_url
