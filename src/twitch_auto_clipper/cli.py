"""Command-line interface for the first local clipping workflow."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

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
from .video import create_vertical_clip, validate_clip_times
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