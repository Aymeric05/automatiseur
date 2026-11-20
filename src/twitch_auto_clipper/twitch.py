"""Twitch VOD acquisition helpers."""

from pathlib import Path
import subprocess
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


def vod_url(vod_id: str) -> str:
    """Twitch URL of a VOD; a live part's id ("<vod id>p<n>", see LIVE_PART_SECONDS) names its VOD."""
    return f"https://www.twitch.tv/videos/{str(vod_id).split('p')[0]}"


def audio_offset(path: Path | str) -> float:
    """Where a downloaded audio file starts in its VOD (seconds): 0 unless only its end was kept."""
    try:
        return float(Path(path).with_name(f"{Path(path).stem}.offset").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0.0


def download_twitch_vod(
    url: str,
    output_dir: Path,
    max_seconds: float | None = None,
    max_height: int | None = None,
    audio_only: bool = False,
    quiet: bool = False,
    rate_limit: int | None = None,
    last_seconds: float | None = None,
    section: tuple[float, float | None] | None = None,
    name: str | None = None,
) -> Path:
    """Download a Twitch VOD and return its local path.

    ``last_seconds`` keeps only the end of a longer VOD (a 48 h stream: its last 8 hours);
    where the file starts in the VOD is written next to it (see ``audio_offset``).

    The video is saved as ``<vod_id>.mp4``; with ``audio_only`` only the audio
    track is saved, as ``<vod_id>_audio.<ext>`` (~70 MB per hour instead of
    several GB): it is all the transcription needs, the Shorts then read their
    few seconds of video straight from Twitch. ``max_seconds`` keeps only the
    beginning of the VOD and ``max_height`` caps the resolution (test runs).
    ``rate_limit`` caps the download speed (bytes per second).
    ``section`` (start, end or None for "until now") downloads only that part of the VOD's audio,
    saved as ``<name>_audio.m4a`` with its start written next to it: a part of a stream still live.
    """
    if not is_twitch_vod_url(url):
        raise ValueError("L'URL doit etre une URL HTTPS de VOD Twitch valide.")

    output_dir.mkdir(parents=True, exist_ok=True)
    if section:
        return _download_section(urlparse(url).path.rstrip("/").split("/")[-1], output_dir, section, name, rate_limit)
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
        "concurrent_fragment_downloads": 4,  # Twitch serves 10 s pieces: several at once, under the rate limit
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
        duration = float(info.get("duration") or 0)
        if last_seconds and duration > last_seconds and downloaded_path.is_file():
            # Cut locally (a few seconds, no re-encoding): downloading only a section through
            # FFmpeg runs slower than real time on Twitch's HLS.
            offset = duration - last_seconds
            kept = downloaded_path.with_name(f"{downloaded_path.stem}.tail{downloaded_path.suffix}")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{offset:.3f}", "-i", str(downloaded_path),
                            "-vn", "-c", "copy", str(kept)], stdin=subprocess.DEVNULL, check=True, timeout=1800)
            kept.replace(downloaded_path)
            downloaded_path.with_name(f"{downloaded_path.stem}.offset").write_text(f"{offset:.3f}", encoding="utf-8")
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


def _download_section(
    vod_id: str, output_dir: Path, section: tuple[float, float | None], name: str | None, rate_limit: int | None,
) -> Path:
    """Audio of one stretch of a VOD (one still live included), through TwitchDownloaderCLI.

    It fetches the 10 s pieces in parallel: 2 hours in ~20 s (2026-11-18), where a yt-dlp
    section (FFmpeg reading the HLS) ran at about real time.
    """
    from .twitch_chat import find_twitch_downloader_cli

    cli = find_twitch_downloader_cli()
    if cli is None:
        raise TwitchDownloadError("TwitchDownloaderCLI est requis pour telecharger une partie de live.")
    start, end = section
    path = output_dir / f"{name or vod_id}_audio.m4a"
    threads = 4
    command = [cli, "videodownload", "--id", vod_id, "-q", "Audio", "-b", f"{int(start)}s",
               *(["-e", f"{int(end)}s"] if end is not None else []), "-o", str(path), "--collision", "Overwrite",
               "-t", str(threads), *(["--bandwidth", str(max(1, rate_limit // 1024 // threads))] if rate_limit else [])]
    try:
        subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace", check=True, timeout=3600)
    except (OSError, subprocess.SubprocessError) as error:
        detail = getattr(error, "stderr", "") or ""
        raise TwitchDownloadError(f"Echec du telechargement de la partie : {error} {detail[-300:]}") from error
    if not path.is_file() or path.stat().st_size == 0:
        raise TwitchDownloadError(f"Partie de live telechargee mais introuvable : {path}")
    path.with_name(f"{path.stem}.offset").write_text(f"{int(start)}.000", encoding="utf-8")
    return path


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
