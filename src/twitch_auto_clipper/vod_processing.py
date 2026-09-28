"""Transcription and chat processing for acquired Twitch VODs."""

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable

from .chat_activity import ChatActivityError, load_chat_messages
from .transcription import save_transcription, transcribe_video
from .twitch_chat import TwitchChatDownloadError, download_twitch_chat
from .vod_acquisition import VODAcquisitionResult


@dataclass(frozen=True)
class VODProcessingResult:
    stream_id: str
    vod_id: str
    broadcaster_id: str
    broadcaster_login: str
    broadcaster_name: str
    clip_budget: int
    transcript_path: Path
    chat_path: Path
    timestamped_chat_path: Path
    transcription_status: str
    chat_status: str
    errors: tuple[str, ...] = ()


class VODProcessingPipeline:
    """Create and persist transcript/chat artifacts once per acquired VOD."""

    def __init__(
        self,
        output_dir: Path = Path("data/output"),
        transcriber: Callable[..., list[dict[str, Any]]] | None = None,
        chat_downloader: Callable[[str, Path], Path] | None = None,
    ) -> None:
        self.output_dir = output_dir
        self.transcriber = transcriber or transcribe_video
        self.chat_downloader = chat_downloader or download_twitch_chat

    def process(self, acquisition: VODAcquisitionResult) -> VODProcessingResult:
        if (
            acquisition.status not in {"downloaded", "already_downloaded", "already_processed"}
            or acquisition.vod_id is None
            or acquisition.downloaded_path is None
        ):
            raise ValueError("VOD acquisition result is not ready for processing.")

        vod_id = acquisition.vod_id
        transcript_path = self.output_dir / f"{vod_id}_transcript.json"
        chat_path = self.output_dir / f"{vod_id}_chat.json"
        timestamped_chat_path = self.output_dir / f"{vod_id}_chat_timestamps.json"
        manifest_path = self.output_dir / f"{vod_id}_processing.json"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        manifest = self._load_manifest(manifest_path)
        manifest.update(
            {
                "stream_id": acquisition.stream_id,
                "vod_id": vod_id,
                "broadcaster_id": acquisition.broadcaster_id,
                "broadcaster_login": acquisition.broadcaster_login,
                "broadcaster_name": acquisition.broadcaster_name,
                "clip_budget": acquisition.clip_budget,
                "source_path": str(acquisition.downloaded_path),
                "transcript_path": str(transcript_path),
                "chat_path": str(chat_path),
                "timestamped_chat_path": str(timestamped_chat_path),
            }
        )

        errors: list[str] = []
        transcription_status = "already_completed"
        if self._valid_json_list(transcript_path):
            manifest["transcription_complete"] = True
        else:
            transcription_status = "completed"
            try:
                segments = self.transcriber(
                    acquisition.downloaded_path,
                    device="cpu",
                    compute_type="int8",
                )
                save_transcription(segments, transcript_path)
                manifest["transcription_complete"] = True
                self._save_manifest(manifest_path, manifest)
            except Exception as error:
                transcription_status = "error"
                manifest["transcription_complete"] = False
                manifest["transcription_error"] = str(error)
                errors.append(f"transcription: {error}")
                self._save_manifest(manifest_path, manifest)

        if manifest.get("chat_status") == "downloaded" and self._valid_json_list(
            timestamped_chat_path
        ):
            chat_status = "already_completed"
        else:
            # Unavailable chat (missing or failed TwitchDownloaderCLI) is retried
            # on every later run; an existing raw chat file is reused.
            chat_status = self._process_chat(
                acquisition.vod_id,
                chat_path,
                timestamped_chat_path,
                manifest,
                errors,
            )
        self._save_manifest(manifest_path, manifest)

        return VODProcessingResult(
            stream_id=acquisition.stream_id,
            vod_id=vod_id,
            broadcaster_id=acquisition.broadcaster_id,
            broadcaster_login=acquisition.broadcaster_login,
            broadcaster_name=acquisition.broadcaster_name,
            clip_budget=acquisition.clip_budget,
            transcript_path=transcript_path,
            chat_path=chat_path,
            timestamped_chat_path=timestamped_chat_path,
            transcription_status=transcription_status,
            chat_status=chat_status,
            errors=tuple(errors),
        )

    def _process_chat(
        self,
        vod_id: str,
        chat_path: Path,
        timestamped_chat_path: Path,
        manifest: dict[str, Any],
        errors: list[str],
    ) -> str:
        vod_url = f"https://www.twitch.tv/videos/{vod_id}"
        try:
            reused_existing_chat = chat_path.is_file() and chat_path.stat().st_size > 0
            if not reused_existing_chat:
                self.chat_downloader(vod_url, chat_path)
            messages = load_chat_messages(chat_path)
            timestamped_chat_path.write_text(
                json.dumps(messages, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except (TwitchChatDownloadError, ChatActivityError, OSError, ValueError) as error:
            manifest["chat_attempted"] = True
            manifest["chat_status"] = "unavailable"
            manifest["chat_error"] = str(error)
            errors.append(f"chat: {error}")
            return "unavailable"

        manifest["chat_attempted"] = True
        manifest["chat_status"] = "downloaded"
        manifest.pop("chat_error", None)
        return "already_completed" if reused_existing_chat else "downloaded"

    @staticmethod
    def _load_manifest(path: Path) -> dict[str, Any]:
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Unable to read VOD processing state: {error}") from error
        if not isinstance(manifest, dict):
            raise ValueError("VOD processing state has an invalid format.")
        return manifest

    @staticmethod
    def _save_manifest(path: Path, manifest: dict[str, Any]) -> None:
        temporary_path = path.with_name(f"{path.name}.tmp")
        temporary_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(path)

    @staticmethod
    def _valid_json_list(path: Path) -> bool:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return isinstance(value, list)


def format_vod_processing_result(result: VODProcessingResult) -> list[str]:
    lines = [
        f"Transcription {result.vod_id} : {result.transcription_status} "
        f"({result.transcript_path})",
        f"Chat {result.vod_id} : {result.chat_status} ({result.chat_path})",
    ]
    lines.extend(f"Erreur {error}" for error in result.errors)
    return lines