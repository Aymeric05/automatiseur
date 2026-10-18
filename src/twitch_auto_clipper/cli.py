"""Command-line interface for the first local clipping workflow."""

import argparse
from functools import partial
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from threading import Event, Lock, Thread

from .audio_events import detect_emotions
from .candidate_clip import CandidateClipError, generate_clip_from_candidate
from .chat_activity import ChatActivityError, add_chat_messages, add_chat_signals, load_chat_messages
from .focus import find_focus
from .streamer_lists import load_streamer_list, load_top_streamers
from .gemini_evaluation import (
    GeminiEvaluationError,
    load_json,
    rank_reserve,
    select_candidate,
)
from .subtitles import generate_ass_subtitles, SubtitleGenerationError
from .twitch_api import TwitchAPIClient, TwitchAPIError
from .twitch_monitor import TwitchStreamMonitor, format_monitoring_cycle
from .video import create_vertical_clip, validate_clip_times
from .vod_acquisition import (
    TwitchVODAcquisitionManager,
    VODAcquisitionResult,
    VODMonitoringCycle,
    find_downloaded_audio,
    format_vod_acquisition_result,
)
from .shorts_upload import VODShortsUploader, format_short_upload_result
from .twitch import TwitchDownloadError, download_twitch_vod, resolve_twitch_video_url
from .twitch_chat import download_twitch_chat, find_twitch_downloader_cli
from .vod_shorts import VODShortsGenerator
from .vod_highlights import VODHighlightSelector
from .vod_pipeline import (
    VODAutomationPipeline,
    format_vod_automation_result,
    process_due_vods,
)
from .vod_processing import VODProcessingPipeline
from .youtube import (
    ANALYTICS_TOKEN_NAME,
    authorize_youtube_analytics,
    fetch_video_retention,
    YouTubeUploadError,
    authenticate_youtube,
    confirm_privacy_policy,
    confirm_upload_rights,
    upload_video,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extrait un passage d'une video locale et le convertit en 9:16."
    )
    parser.add_argument(
        "--upload-youtube",
        action="store_true",
        help="Publie une video sur YouTube via OAuth 2.0.",
    )
    parser.add_argument(
        "--list-twitch-streams",
        action="store_true",
        help="Liste les streams Twitch anglais les plus regardes.",
    )
    parser.add_argument(
        "--monitor-twitch-once",
        action="store_true",
        help="Surveille les streams Twitch pendant un cycle de polling.",
    )
    parser.add_argument(
        "--monitor-twitch",
        action="store_true",
        help="Surveille Twitch en continu et acquiert les VOD apres la fin des streams.",
    )
    parser.add_argument(
        "--monitor-interval",
        type=float,
        default=60.0,
        help="Intervalle de surveillance en secondes (defaut : 60).",
    )
    parser.add_argument(
        "--process-vod",
        metavar="VOD",
        help=(
            "Traite une VOD Twitch terminee (id ou URL) sans monitoring : telechargement si "
            "necessaire, transcription, chat, Gemini, Shorts et metadonnees. Jamais d'upload."
        ),
    )
    parser.add_argument(
        "--clip-budget",
        type=int,
        default=2,
        help="Avec --process-vod : nombre de Shorts vises (defaut : 2).",
    )
    parser.add_argument(
        "--test-minutes",
        type=float,
        help=(
            "Avec --process-vod : ne telecharge que les N premieres minutes, en 720p max, "
            "dans data/test/ (separe des donnees de production)."
        ),
    )
    parser.add_argument(
        "--verbose-streams",
        action="store_true",
        help="Avec --monitor-twitch(-once) : liste chaque stream suivi et chaque changement de viewers.",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Indique quelles integrations sont configurees (oui/non), sans afficher de secret.",
    )
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        help="Avec --monitor-twitch : s'arrete apres ce nombre de cycles (defaut : illimite).",
    )
    parser.add_argument(
        "--auto-upload-youtube",
        action="store_true",
        help=(
            "Avec --monitor-twitch(-once) : publie automatiquement les Shorts "
            "generes en prive sur YouTube, puis supprime le fichier local "
            "apres confirmation de l'upload."
        ),
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        help="Ecrit la sortie dans ce fichier, limite en taille (demarrage automatique).",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help=(
            "Avec --auto-upload-youtube : confirme d'avance les droits de publication et la "
            "Privacy Policy (demarrage automatique, sans clavier)."
        ),
    )
    parser.add_argument(
        "--stream-limit",
        type=int,
        default=20,
        help="Nombre maximum de streams a afficher (defaut : 20).",
    )
    parser.add_argument("--video", type=Path, help="Fichier video a publier.")
    parser.add_argument("--title", help="Titre de la video YouTube.")
    parser.add_argument("--description", default="", help="Description YouTube.")
    parser.add_argument(
        "--privacy",
        choices=("private", "unlisted", "public"),
        default="private",
        help="Visibilite YouTube (defaut : private).",
    )
    made_for_kids = parser.add_mutually_exclusive_group()
    made_for_kids.add_argument(
        "--made-for-kids",
        dest="made_for_kids",
        action="store_true",
        help="Declare la video comme destinee aux enfants.",
    )
    made_for_kids.add_argument(
        "--not-made-for-kids",
        dest="made_for_kids",
        action="store_false",
        help="Declare la video comme non destinee aux enfants.",
    )
    parser.set_defaults(made_for_kids=None)
    parser.add_argument(
        "--youtube-client-secrets",
        type=Path,
        default=Path("credentials.json"),
        help="Fichier OAuth client secret local.",
    )
    parser.add_argument(
        "--youtube-token",
        type=Path,
        default=Path("youtube-token.json"),
        help="Fichier local du token OAuth.",
    )
    parser.add_argument(
        "--authorize-youtube-analytics",
        action="store_true",
        help="Autorise une fois la lecture de la retention des Shorts (YouTube Analytics).",
    )
    parser.add_argument(
        "--auto-clip",
        action="store_true",
        help="Selectionne un candidat avec Gemini puis genere le clip.",
    )
    parser.add_argument(
        "--generate-from-candidate",
        action="store_true",
        help="Genere un clip vertical depuis un candidat JSON.",
    )
    parser.add_argument("--source", help="Chemin de la video source.")
    parser.add_argument(
        "--candidate-json",
        "--candidates-json",
        dest="candidate_json",
        type=Path,
        help="Fichier *_highlights.json.",
    )
    parser.add_argument("--candidate-index", type=int, help="Index zero-based du candidat.")
    parser.add_argument(
        "--transcript-json",
        type=Path,
        help="Transcription JSON optionnelle pour les sous-titres.",
    )
    parser.add_argument("--before", type=float, default=5.0)
    parser.add_argument("--after", type=float, default=5.0)
    parser.add_argument("--chat-json", type=Path, help="JSON du chat optionnel.")
    parser.add_argument("--chat-window", type=float, default=30.0)
    parser.add_argument("--gemini-model", default="gemini-3.6-flash")
    parser.add_argument("input", nargs="?", help="Nom du fichier present dans data/input/.")
    parser.add_argument("start", type=float, nargs="?", help="Debut du clip en secondes.")
    parser.add_argument("end", type=float, nargs="?", help="Fin du clip en secondes.")
    parser.add_argument(
        "--output",
        help="Nom du fichier de sortie dans data/output/ (optionnel).",
    )
    parser.add_argument(
        "--subtitles",
        type=Path,
        help="JSON de transcription avec timestamps mot par mot.",
    )
    return parser


ENV_FILE = Path(".env")  # optional KEY=value file at the project root, ignored by git
DATA_DIR = Path("data")  # production data; --test-minutes uses DATA_DIR / "test"
WORKER_IDLE_SECONDS = 30.0  # pause of the VOD worker when no job is due
PUBLISH_IDLE_SECONDS = 60.0  # how often the publisher checks for a due upload
TOP_STREAMERS_FILE = Path("top_streamers.txt")
FAVORED_STREAMERS_FILE = Path("favored_streamers.txt")
# No Short is ever made from these streamers (read again at each use: the app adds to it).
BLOCKED_STREAMERS_FILE = Path("blocked_streamers.txt")
PUBLISH_RETRY_SECONDS = 1800.0  # pause after a failed upload (network, sign-in...)
DEFAULT_DOWNLOAD_KBPS = 1000  # VOD audio download cap (~8 Mbit/s); DOWNLOAD_MAX_KBPS overrides it
DEFAULT_DAILY_UPLOADS = 10  # YouTube refused the 11th upload of the day (default quota)
DEFAULT_DAILY_GEMINI_REQUESTS = 20  # Gemini API free tier, per model and per day (each model)


def _daily_limit(parser: argparse.ArgumentParser, name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name) or default)
        if value < 1:
            raise ValueError
    except ValueError:
        parser.error(f"{name} doit etre un entier positif.")
    return value


LOG_MAX_BYTES = 10 * 1024 * 1024  # about two days of monitoring per file


class RotatingLog:
    """stdout and stderr of the unattended app, written to ``path``.

    Past ``max_bytes`` the file is renamed ``<name>.old<suffix>`` (replacing
    the previous one) and a new one starts: the log never takes more than
    twice ``max_bytes``.
    """

    encoding = "utf-8"

    def __init__(self, path: Path, max_bytes: int = LOG_MAX_BYTES) -> None:
        self.path = path
        self.max_bytes = max_bytes
        self._lock = Lock()  # the monitoring, worker and publisher threads all print
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(path, "a", encoding="utf-8", errors="replace")

    def write(self, text: str) -> int:
        with self._lock:
            self._file.write(text)
            self._file.flush()
            if self._file.tell() > self.max_bytes:
                self._file.close()
                try:
                    os.replace(self.path, self.path.with_name(f"{self.path.stem}.old{self.path.suffix}"))
                except OSError:
                    pass  # opened by another process right now: rotated on a later write
                self._file = open(self.path, "a", encoding="utf-8", errors="replace")
        return len(text)

    def flush(self) -> None:
        with self._lock:
            self._file.flush()

    def isatty(self) -> bool:
        return False


def kill_children_with_this_process() -> None:
    """On Windows, make FFmpeg and TwitchDownloaderCLI die with the app.

    Closing the console window kills Python only: a chat download or a render
    would otherwise keep running, and keep using the network. Every child
    process joins a job object that Windows closes when this process ends.
    """
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimits), ("IoInfo", ctypes.c_uint64 * 6),
            ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    job = kernel32.CreateJobObjectW(None, None)  # never closed: Windows closes it at exit
    limits = ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not job or not kernel32.SetInformationJobObject(
        job, 9, ctypes.byref(limits), ctypes.sizeof(limits)  # 9: extended limit information
    ) or not kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess()):
        print("Avertissement : les processus enfants ne s'arreteront pas avec l'application.", file=sys.stderr)


def acquire_instance_lock(path: Path):
    """Return an open lock handle, or None when another process holds the lock.

    The operating system releases the lock when the process ends, even after
    a crash, so a stale lock never blocks the next start.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+", encoding="utf-8")
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def _twitch_video(acquisition: VODAcquisitionResult) -> str:
    """Stream URL of the VOD video: each Short reads only its own seconds from Twitch."""
    return resolve_twitch_video_url(f"https://www.twitch.tv/videos/{acquisition.vod_id}")


def load_env_file(path: Path) -> None:
    """Set KEY=value pairs from an optional .env file; real environment variables win."""
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return
    except OSError as error:
        print(f"Avertissement : {path} illisible ({error}).", file=sys.stderr)
        return
    # Windows editors may add a UTF-8 BOM; PowerShell 5.1 ">" writes UTF-16.
    encoding = "utf-16" if data[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
    for line in data.decode(encoding, errors="replace").splitlines():
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or not key or key.startswith("#") or "\0" in line:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def config_report(args: argparse.Namespace) -> list[tuple[str, bool, bool]]:
    """Return (label, configured, required_for_monitoring) without reading secrets."""
    def env(name: str) -> bool:
        return bool(os.environ.get(name, "").strip())

    def module(name: str) -> bool:
        return importlib.util.find_spec(name) is not None

    return [
        ("TWITCH_CLIENT_ID", env("TWITCH_CLIENT_ID"), True),
        ("TWITCH_CLIENT_SECRET", env("TWITCH_CLIENT_SECRET"), True),
        ("GEMINI_API_KEY", env("GEMINI_API_KEY"), True),
        ("FFmpeg / FFprobe dans le PATH", bool(shutil.which("ffmpeg") and shutil.which("ffprobe")), True),
        ("yt-dlp installe", module("yt_dlp"), True),
        ("faster-whisper installe", module("faster_whisper"), True),
        ("google-genai installe", module("google.genai"), True),
        ("TwitchDownloaderCLI (tools/ ou PATH, chat)", find_twitch_downloader_cli() is not None, False),
        ("YOUTUBE_PRIVACY_POLICY_URL (upload)", env("YOUTUBE_PRIVACY_POLICY_URL"), False),
        ("YOUTUBE_EXPECTED_CHANNEL_ID (verification de chaine)", env("YOUTUBE_EXPECTED_CHANNEL_ID"), False),
        ("Fichier OAuth YouTube (upload)", args.youtube_client_secrets.is_file(), False),
        ("Token YouTube local (upload)", args.youtube_token.is_file(), False),
    ]


def process_vod(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Run the VOD pipeline on one finished VOD. Publication is never enabled."""
    if args.auto_upload_youtube or args.upload_youtube:
        parser.error("--process-vod ne publie jamais : retirez l'option d'upload YouTube.")
    if args.clip_budget < 1:
        parser.error("--clip-budget doit etre positif.")
    if args.test_minutes is not None and args.test_minutes <= 0:
        parser.error("--test-minutes doit etre positif.")
    vod_id = args.process_vod.rstrip("/").split("/")[-1]
    if not vod_id.isdigit():
        parser.error("--process-vod attend un id numerique ou une URL twitch.tv/videos/<id>.")

    root = DATA_DIR / "test" if args.test_minutes else DATA_DIR
    input_dir, output_dir = root / "input", root / "output"
    try:
        client = TwitchAPIClient()
        vod = client.fetch_vod(vod_id)
        if vod is None:
            print(f"VOD {vod_id} introuvable sur Twitch.", file=sys.stderr)
            return 1
        # A VOD of a stream still on air keeps growing: refuse it. Any API
        # error here propagates to the handler below and stops processing.
        live = client.fetch_live_streams_by_user_ids([vod.broadcaster_id]).get(vod.broadcaster_id)
        if live is not None and (not vod.stream_id or live.stream_id == vod.stream_id):
            print(
                f"VOD {vod_id} refusee : le stream {vod.broadcaster_name} est encore en cours"
                + ("." if vod.stream_id else " (stream_id de la VOD inconnu, fin non verifiable)."),
                file=sys.stderr,
            )
            return 1
        # Only the audio is downloaded for the transcription; each Short then reads
        # its few seconds of video from Twitch, on the same timeline as the chat.
        source = find_downloaded_audio(input_dir, vod_id)
        if source is not None:
            print(f"Audio de la VOD deja present : {source}")
        else:
            print(f"Telechargement de l'audio de la VOD {vod_id} vers {input_dir} ...")
            source = download_twitch_vod(
                f"https://www.twitch.tv/videos/{vod_id}",
                input_dir,
                max_seconds=args.test_minutes * 60 if args.test_minutes else None,
                audio_only=True,
            )
    except (TwitchAPIError, TwitchDownloadError, OSError, ValueError) as error:
        print(f"Erreur : {error}", file=sys.stderr)
        return 1

    acquisition = VODAcquisitionResult(
        stream_id=vod.stream_id,
        clip_budget=args.clip_budget,
        status="downloaded",
        broadcaster_id=vod.broadcaster_id,
        broadcaster_login=vod.broadcaster_login,
        broadcaster_name=vod.broadcaster_name,
        vod_id=vod_id,
        downloaded_path=source,
    )
    # Test mode: only the chat of the downloaded extract.
    chat_downloader = (
        partial(download_twitch_chat, end_seconds=args.test_minutes * 60)
        if args.test_minutes
        else None
    )
    automation = VODAutomationPipeline(
        processing_pipeline=VODProcessingPipeline(
            output_dir, chat_downloader=chat_downloader, emotion_detector=detect_emotions
        ),
        highlight_selector=VODHighlightSelector(
            output_dir,
            model=args.gemini_model,
            gemini_daily_limit=_daily_limit(
                parser, "GEMINI_MAX_REQUESTS_PER_DAY", DEFAULT_DAILY_GEMINI_REQUESTS
            ),
        ),
        shorts_generator=VODShortsGenerator(output_dir),
        output_dir=output_dir,
        video_source=_twitch_video,
    )
    result = automation.run(acquisition)
    is_failure = result.status != "completed"
    for line in format_vod_automation_result(result):
        print(line, file=sys.stderr if is_failure else sys.stdout)
    return 1 if is_failure else 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        # Redirected to a file, Windows would write cp1252 and crash on the
        # first emoji of a stream title: write UTF-8 instead.
        if hasattr(stream, "reconfigure") and not stream.isatty():
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass
    load_env_file(ENV_FILE)
    parser = build_parser()
    args = parser.parse_args()
    if args.log_file:
        sys.stdout = sys.stderr = RotatingLog(args.log_file)

    if args.check_config:
        report = config_report(args)
        for label, configured, required in report:
            print(f"{'oui' if configured else 'NON'}  {label}{'' if required else ' [optionnel]'}")
        return 0 if all(configured for _, configured, required in report if required) else 1

    if args.process_vod:
        return process_vod(args, parser)

    if args.authorize_youtube_analytics:
        try:
            authorize_youtube_analytics(args.youtube_client_secrets, args.youtube_token.with_name(ANALYTICS_TOKEN_NAME))
        except Exception as error:
            print(f"Erreur : {error}", file=sys.stderr)
            return 1
        print("Retention YouTube autorisee : elle sera lue avec les vues, toutes les 6 heures.")
        return 0

    if args.monitor_twitch_once or args.monitor_twitch:
        if args.monitor_interval <= 0:
            parser.error("--monitor-interval doit etre positif.")
        if args.max_cycles is not None and args.max_cycles < 1:
            parser.error("--max-cycles doit etre positif.")
        kill_children_with_this_process()
        download_kbps = _daily_limit(parser, "DOWNLOAD_MAX_KBPS", DEFAULT_DOWNLOAD_KBPS)
        daily_uploads = _daily_limit(parser, "YOUTUBE_MAX_UPLOADS_PER_DAY", DEFAULT_DAILY_UPLOADS)
        daily_gemini = _daily_limit(parser, "GEMINI_MAX_REQUESTS_PER_DAY", DEFAULT_DAILY_GEMINI_REQUESTS)
        upload_privacy = os.environ.get("YOUTUBE_PRIVACY", "").strip().lower() or "private"
        if upload_privacy not in {"private", "unlisted", "public"}:
            parser.error("YOUTUBE_PRIVACY doit valoir private, unlisted ou public.")
        input_dir, output_dir = DATA_DIR / "input", DATA_DIR / "output"
        favored_streamers = load_top_streamers(FAVORED_STREAMERS_FILE)
        # Favored streamers are handled like the top list, plus a ranking bonus.
        top_streamers = load_top_streamers(TOP_STREAMERS_FILE) | favored_streamers
        # Two monitors would download, process and publish the same VODs twice.
        instance_lock = acquire_instance_lock(output_dir / ".monitor.lock")
        if instance_lock is None:
            print("Erreur : une autre surveillance Twitch tourne deja sur ces donnees.", file=sys.stderr)
            return 1
        # Transcription chunks left by a run cut short (closed window, sleep, crash).
        shutil.rmtree(output_dir / "tmp", ignore_errors=True)
        monitor = TwitchStreamMonitor(
            polling_interval_seconds=args.monitor_interval,
            state_path=output_dir / "twitch_monitor_state.json",
        )
        try:
            manager = TwitchVODAcquisitionManager(
                monitor=monitor,
                input_dir=input_dir,
                state_path=output_dir / "twitch_vod_state.json",
                top_streamers=top_streamers,
                rate_limit=download_kbps * 1024,
                blocked_streamers=partial(load_top_streamers, BLOCKED_STREAMERS_FILE),
            )
        except ValueError as error:
            print(f"Erreur d'etat VOD : {error}", file=sys.stderr)
            return 1
        uploader = None
        if args.auto_upload_youtube:
            expected_channel_id = os.environ.get("YOUTUBE_EXPECTED_CHANNEL_ID", "")
            if not expected_channel_id:
                print(
                    "Avertissement : YOUTUBE_EXPECTED_CHANNEL_ID n'est pas configuree; "
                    "la verification de chaine n'est pas active.",
                    file=sys.stderr,
                )
            # --yes answers both questions (they are still printed in the log).
            answer = (lambda _question: "oui") if args.yes else input
            try:
                if not confirm_upload_rights(input_func=answer):
                    print("Upload automatique annule : droits non confirmes.", file=sys.stderr)
                    return 1
                if not confirm_privacy_policy(
                    os.environ.get("YOUTUBE_PRIVACY_POLICY_URL", ""), input_func=answer
                ):
                    print("Upload automatique annule : Privacy Policy non acceptee.", file=sys.stderr)
                    return 1
                # Authenticate now, while the user is present: an expired or
                # missing token would otherwise open the OAuth browser flow in
                # the middle of unattended monitoring and block the worker.
                authenticate_youtube(
                    args.youtube_client_secrets,
                    args.youtube_token,
                    expected_channel_id or None,
                )
            except YouTubeUploadError as error:
                print(f"Erreur : {error}", file=sys.stderr)
                return 1
            uploader = VODShortsUploader(
                output_dir=output_dir,
                client_secrets_path=args.youtube_client_secrets,
                token_path=args.youtube_token,
                expected_channel_id=expected_channel_id or None,
                daily_upload_limit=daily_uploads,
                privacy=upload_privacy,
                top_streamers=top_streamers,
                favored_streamers=favored_streamers,
                streamer_ranks={
                    login: rank for rank, login in enumerate(load_streamer_list(TOP_STREAMERS_FILE), start=1)
                },
                check_seconds=PUBLISH_IDLE_SECONDS,
                blocked_streamers_path=BLOCKED_STREAMERS_FILE,
                retention_fetcher=partial(
                    fetch_video_retention,
                    client_secrets_path=args.youtube_client_secrets,
                    token_path=args.youtube_token.with_name(ANALYTICS_TOKEN_NAME),
                ),
                arbiter=partial(
                    rank_reserve, model=args.gemini_model, quota_dir=output_dir, daily_limit=daily_gemini
                ),
            )
        automation = VODAutomationPipeline(
            processing_pipeline=VODProcessingPipeline(output_dir, emotion_detector=detect_emotions),
            highlight_selector=VODHighlightSelector(
                output_dir,
                model=args.gemini_model,
                gemini_daily_limit=daily_gemini,
            ),
            shorts_generator=VODShortsGenerator(output_dir),
            output_dir=output_dir,
            video_source=_twitch_video,  # no full VOD video on disk
            delete_sources_on_success=True,  # audio and chat, once the VOD is completed
            # Screen-sharing streams: each Short centered on what matters, not on the middle.
            focus_finder=partial(find_focus, quota_dir=output_dir, daily_limit=daily_gemini),
        )

        def report(line: str, is_error: bool = False) -> None:
            print(line, file=sys.stderr if is_error else sys.stdout, flush=True)

        def report_cycle(result: VODMonitoringCycle) -> None:
            cycle = result.monitoring_cycle
            for line in format_monitoring_cycle(cycle, verbose=args.verbose_streams):
                report(line, bool(cycle.error))
            for acquisition_result in result.acquisition_results:
                report(format_vod_acquisition_result(acquisition_result), acquisition_result.status == "error")

        def publish_next() -> bool:
            """Upload the best ready Short if an upload is due; False after a failure."""
            try:
                summary = uploader.refresh_statistics()  # once a day
            except Exception as error:  # statistics never stop the publications
                summary = f"Statistiques YouTube non lues : {error!r}"
            if summary:
                report(summary)
            try:
                published = uploader.publish_next()
            except Exception as error:  # keep the publisher alive; Shorts stay on disk
                report(f"Erreur de publication : {error!r}", True)
                return False
            if published is None:
                return True
            vod_id, upload = published
            failed = upload.status == "error"
            report(f"Publication VOD {vod_id} : {format_short_upload_result(upload).strip()} | {upload.title}", failed)
            return not failed

        stop = Event()
        try:
            if args.monitor_twitch_once:
                try:
                    result = manager.poll_once()
                except (OSError, ValueError) as error:
                    print(f"Erreur VOD : {error}", file=sys.stderr)
                    return 1
                report_cycle(result)
                process_due_vods(manager, automation, report)  # queued VODs, this one included
                if uploader is not None:
                    publish_next()
                return 1 if result.monitoring_cycle.error else 0

            # The monitoring loop only queues ended streams; this worker downloads,
            # transcribes, selects and renders, so a long VOD never pauses the
            # monitoring. Every job is persisted: if the program stops mid-way,
            # the next start picks it up again. The publisher uploads the day's
            # best ready Shorts during the publication hour.
            def work() -> None:
                while not stop.is_set():
                    try:
                        process_due_vods(manager, automation, report)
                    except Exception as error:  # keep the worker alive; jobs stay queued
                        report(f"Erreur du traitement des VOD : {error!r}", True)
                    stop.wait(WORKER_IDLE_SECONDS)

            def publish() -> None:
                while not stop.is_set():
                    stop.wait(PUBLISH_IDLE_SECONDS if publish_next() else PUBLISH_RETRY_SECONDS)

            Thread(target=work, name="vod-worker", daemon=True).start()
            if uploader is not None:
                Thread(target=publish, name="shorts-publisher", daemon=True).start()
            manager.run(report_cycle, stop, max_cycles=args.max_cycles)
        except KeyboardInterrupt:
            print("Surveillance Twitch arretee. Les VOD en cours ou en attente reprendront au prochain lancement.")
            return 130
        finally:
            stop.set()
            instance_lock.close()
        if manager.pending_jobs:
            print(f"{manager.pending_jobs} VOD en attente : traitement repris au prochain lancement.")
        return 0

    if args.list_twitch_streams:
        if args.stream_limit < 1:
            parser.error("--stream-limit doit etre positif.")
        try:
            streams = TwitchAPIClient().fetch_english_streams(limit=args.stream_limit)
        except TwitchAPIError as error:
            print(f"Erreur Twitch : {error}", file=sys.stderr)
            return 1
        for stream in streams:
            print(
                f"{stream.viewer_count:>8} viewers | {stream.broadcaster_name} "
                f"(@{stream.broadcaster_login}) | {stream.game_name} | {stream.title}"
            )
        if not streams:
            print("Aucun stream anglais en direct trouve.")
        return 0

    if args.upload_youtube:
        if args.video is None or not args.title:
            parser.error("--upload-youtube requiert --video et --title.")
        if args.made_for_kids is None:
            parser.error(
                "--upload-youtube requiert --made-for-kids ou --not-made-for-kids."
            )
        video_path = args.video
        if not video_path.is_file():
            parser.error(f"Fichier video introuvable : {video_path}")
        privacy_policy_url = os.environ.get("YOUTUBE_PRIVACY_POLICY_URL", "")
        expected_channel_id = os.environ.get("YOUTUBE_EXPECTED_CHANNEL_ID", "")
        if not expected_channel_id:
            print(
                "Avertissement : YOUTUBE_EXPECTED_CHANNEL_ID n'est pas configuree; "
                "la verification de chaine n'est pas active.",
                file=sys.stderr,
            )
        try:
            if not confirm_upload_rights():
                print("Upload annule : les droits de publication n'ont pas ete confirmes.", file=sys.stderr)
                return 1
            if not confirm_privacy_policy(privacy_policy_url):
                print("Upload annule : la Privacy Policy n'a pas ete acceptee.", file=sys.stderr)
                return 1
            video_id, video_url = upload_video(
                video_path,
                args.title,
                args.description,
                args.privacy,
                args.youtube_client_secrets,
                args.youtube_token,
                made_for_kids=args.made_for_kids,
                expected_channel_id=expected_channel_id or None,
            )
        except YouTubeUploadError as error:
            print(f"Erreur : {error}", file=sys.stderr)
            return 1
        print(f"Video YouTube publiee : {video_id}")
        print(f"URL : {video_url}")
        return 0

    if args.auto_clip:
        if not args.source or args.candidate_json is None or args.transcript_json is None:
            parser.error(
                "--auto-clip requiert --source, --candidates-json et --transcript-json."
            )
        source_path = Path(args.source)
        if not source_path.is_file():
            source_path = Path("data/input") / args.source
        if not source_path.is_file():
            parser.error(f"Fichier source introuvable : {args.source}")
        try:
            candidates = load_json(args.candidate_json, "les candidats")
            transcript = load_json(args.transcript_json, "la transcription")
            if not isinstance(candidates, list) or not isinstance(transcript, list):
                raise GeminiEvaluationError(
                    "Les candidats et la transcription doivent etre des listes JSON."
                )
            if args.chat_json:
                messages = load_chat_messages(args.chat_json)
                candidates = add_chat_signals(
                    add_chat_messages(candidates, messages, args.chat_window), messages
                )
            candidate_index, evaluation = select_candidate(
                candidates, transcript, model=args.gemini_model
            )
            output_path = Path("data/output") / (
                f"{source_path.stem}_gemini_candidate_{candidate_index}.mp4"
            )
            output_path, start, end = generate_clip_from_candidate(
                source_path,
                args.candidate_json,
                candidate_index,
                output_path,
                transcript_path=args.transcript_json,
                before=args.before,
                after=args.after,
            )
        except (
            CandidateClipError,
            ChatActivityError,
            GeminiEvaluationError,
            FileNotFoundError,
            ValueError,
        ) as error:
            print(f"Erreur : {error}", file=sys.stderr)
            return 1
        except subprocess.CalledProcessError as error:
            print(f"FFmpeg/FFprobe a echoue avec le code {error.returncode}.", file=sys.stderr)
            return error.returncode or 1
        print(
            f"Clip Gemini cree : {output_path} "
            f"(candidate_{candidate_index + 1}, {start:g}s - {end:g}s)"
        )
        return 0

    if args.generate_from_candidate:
        if not args.source or args.candidate_json is None or args.candidate_index is None:
            parser.error(
                "--generate-from-candidate requiert --source, --candidate-json et --candidate-index."
            )
        source_path = Path(args.source)
        if not source_path.is_file():
            source_path = Path("data/input") / args.source
        if not source_path.is_file():
            parser.error(f"Fichier source introuvable : {args.source}")
        output_path = Path("data/output") / (
            f"{source_path.stem}_candidate_{args.candidate_index}.mp4"
        )
        try:
            output_path, start, end = generate_clip_from_candidate(
                source_path,
                args.candidate_json,
                args.candidate_index,
                output_path,
                transcript_path=args.transcript_json,
                before=args.before,
                after=args.after,
            )
        except (CandidateClipError, FileNotFoundError, ValueError) as error:
            print(f"Erreur : {error}", file=sys.stderr)
            return 1
        except subprocess.CalledProcessError as error:
            print(f"FFmpeg/FFprobe a echoue avec le code {error.returncode}.", file=sys.stderr)
            return error.returncode or 1
        print(f"Clip cree : {output_path} ({start:g}s - {end:g}s)")
        return 0

    if args.input is None or args.start is None or args.end is None:
        parser.error("input, start et end sont requis hors de --generate-from-candidate.")

    try:
        validate_clip_times(args.start, args.end)
    except ValueError as error:
        parser.error(str(error))

    input_path = Path("data/input") / args.input
    if not input_path.is_file():
        parser.error(f"Fichier introuvable : {input_path}")

    output_name = args.output or (
        f"{input_path.stem}_clip_{args.start:g}_{args.end:g}.mp4"
    )
    output_path = Path("data/output") / output_name
    subtitles_path = None

    try:
        if args.subtitles:
            segments = json.loads(args.subtitles.read_text(encoding="utf-8"))
            subtitles_path = output_path.with_suffix(".ass")
            generate_ass_subtitles(
                segments,
                subtitles_path,
                clip_start=args.start,
                clip_end=args.end,
            )
        create_vertical_clip(
            input_path,
            output_path,
            args.start,
            args.end,
            subtitles_path=subtitles_path,
        )
    except (OSError, ValueError, json.JSONDecodeError, SubtitleGenerationError) as error:
        print(f"Erreur : {error}", file=sys.stderr)
        return 1
    except FileNotFoundError:
        print("Erreur : FFmpeg est introuvable dans le PATH.", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as error:
        print(f"FFmpeg a echoue avec le code {error.returncode}.", file=sys.stderr)
        return error.returncode or 1

    print(f"Clip cree : {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())