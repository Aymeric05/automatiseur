"""Command-line interface for the first local clipping workflow."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Event

from .candidate_clip import CandidateClipError, generate_clip_from_candidate
from .chat_activity import ChatActivityError, add_chat_messages, load_chat_messages
from .gemini_evaluation import (
    GeminiEvaluationError,
    evaluate_candidates,
    load_json,
    save_evaluations,
    select_candidate,
)
from .subtitles import generate_ass_subtitles, SubtitleGenerationError
from .twitch_api import TwitchAPIClient, TwitchAPIError
from .twitch_monitor import TwitchStreamMonitor, format_monitoring_cycle
from .video import create_vertical_clip, validate_clip_times
from .vod_acquisition import (
    TwitchVODAcquisitionManager,
    VODMonitoringCycle,
    format_vod_acquisition_result,
)
from .vod_processing import VODProcessingPipeline, format_vod_processing_result
from .youtube import (
    YouTubeUploadError,
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


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.monitor_twitch_once or args.monitor_twitch:
        if args.monitor_interval <= 0:
            parser.error("--monitor-interval doit etre positif.")
        monitor = TwitchStreamMonitor(
            polling_interval_seconds=args.monitor_interval
        )
        try:
            manager = TwitchVODAcquisitionManager(monitor=monitor)
        except ValueError as error:
            print(f"Erreur d'etat VOD : {error}", file=sys.stderr)
            return 1
        processing_pipeline = VODProcessingPipeline()

        def report_cycle(result: VODMonitoringCycle) -> None:
            cycle = result.monitoring_cycle
            for line in format_monitoring_cycle(cycle):
                print(line, file=sys.stderr if cycle.error else sys.stdout)
            for acquisition_result in result.acquisition_results:
                is_error = acquisition_result.status == "error"
                print(
                    format_vod_acquisition_result(acquisition_result),
                    file=sys.stderr if is_error else sys.stdout,
                )
                if (
                    acquisition_result.status
                    not in {"downloaded", "already_downloaded", "already_processed"}
                    or acquisition_result.downloaded_path is None
                ):
                    continue
                try:
                    processing_result = processing_pipeline.process(acquisition_result)
                except (OSError, ValueError) as error:
                    print(f"Erreur de traitement VOD : {error}", file=sys.stderr)
                    continue
                for line in format_vod_processing_result(processing_result):
                    print(line, file=sys.stderr if processing_result.errors else sys.stdout)

        if args.monitor_twitch_once:
            try:
                result = manager.poll_once()
            except (OSError, ValueError) as error:
                print(f"Erreur VOD : {error}", file=sys.stderr)
                return 1
            report_cycle(result)
            has_acquisition_error = any(
                item.status == "error" for item in result.acquisition_results
            )
            return 1 if result.monitoring_cycle.error or has_acquisition_error else 0

        try:
            manager.run(report_cycle, Event())
        except KeyboardInterrupt:
            print("Surveillance Twitch arretee.")
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
                candidates = add_chat_messages(candidates, messages, args.chat_window)
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