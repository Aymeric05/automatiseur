"""YouTube Shorts upload helpers using the official Google APIs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
YOUTUBE_SCOPES = [YOUTUBE_UPLOAD_SCOPE, YOUTUBE_READONLY_SCOPE]


class YouTubeUploadError(RuntimeError):
    """Raised when YouTube authentication or upload fails."""


def _load_google_dependencies():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload
    except ModuleNotFoundError as error:
        raise YouTubeUploadError(
            "Les dependances Google YouTube sont requises pour publier une video."
        ) from error
    return Request, Credentials, InstalledAppFlow, build, HttpError, MediaFileUpload

def confirm_upload_rights(input_func=input, output_func=print) -> bool:
    """Ask the user to confirm rights to publish the selected content."""
    output_func(
        "Attention : vous devez disposer des droits ou autorisations necessaires "
        "pour utiliser et republier ce contenu. Une video Twitch ne vous donne "
        "pas automatiquement ces droits. YouTube applique ses propres regles."
    )
    return input_func("Confirmez-vous ces droits ? [y/N] ").strip().lower() in {
        "y",
        "yes",
        "o",
        "oui",
    }

def confirm_privacy_policy(
    privacy_policy_url: str,
    input_func=input,
    output_func=print,
) -> bool:
    """Ask the user to acknowledge the public project Privacy Policy."""
    if not privacy_policy_url:
        raise YouTubeUploadError(
            "YOUTUBE_PRIVACY_POLICY_URL doit etre configuree avant un upload."
        )
    output_func(f"Privacy Policy du projet : {privacy_policy_url}")
    return input_func("Confirmez-vous avoir acces a cette Privacy Policy ? [y/N] ").strip().lower() in {
        "y",
        "yes",
        "o",
        "oui",
    }


def authenticate_youtube(
    client_secrets_path: Path = Path("credentials.json"),
    token_path: Path = Path("youtube-token.json"),
    expected_channel_id: str | None = None,
):
    """Load or create local OAuth credentials for YouTube uploads."""
    Request, Credentials, InstalledAppFlow, build, _, _ = _load_google_dependencies()
    scopes = [YOUTUBE_UPLOAD_SCOPE]
    if expected_channel_id:
        scopes.append(YOUTUBE_READONLY_SCOPE)
    credentials = None
    try:
        if token_path.is_file():
            credentials = Credentials.from_authorized_user_file(str(token_path), scopes)
            if not credentials.scopes or not set(scopes).issubset(credentials.scopes):
                credentials = None
        if credentials is None or not credentials.valid:
            if credentials is not None and credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
            else:
                if not client_secrets_path.is_file():
                    raise YouTubeUploadError(
                        f"Fichier OAuth introuvable : {client_secrets_path}"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(client_secrets_path), scopes
                )
                credentials = flow.run_local_server(port=0)
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(credentials.to_json(), encoding="utf-8")
        return build("youtube", "v3", credentials=credentials)
    except YouTubeUploadError:
        raise
    except Exception as error:
        raise YouTubeUploadError(f"Echec de l'authentification YouTube : {error}") from error


def get_authenticated_channel_id(youtube_service: Any) -> str:
    """Return the channel ID belonging to the OAuth-authorized account."""
    try:
        response = youtube_service.channels().list(
            part="id,snippet", mine=True
        ).execute()
        channels = response.get("items", [])
        channel_id = channels[0].get("id") if channels else None
        if not channel_id:
            raise YouTubeUploadError("Aucune chaine YouTube n'est associee au compte OAuth.")
        return channel_id
    except YouTubeUploadError:
        raise
    except Exception as error:
        raise YouTubeUploadError(
            f"Impossible de verifier la chaine YouTube authentifiee : {error}"
        ) from error


def verify_expected_channel(youtube_service: Any, expected_channel_id: str | None) -> None:
    """Reject uploads when the configured expected channel does not match."""
    if not expected_channel_id:
        return
    actual_channel_id = get_authenticated_channel_id(youtube_service)
    if actual_channel_id != expected_channel_id:
        raise YouTubeUploadError(
            "La chaine YouTube OAuth ne correspond pas a YOUTUBE_EXPECTED_CHANNEL_ID."
        )


def upload_video(
    video_path: Path,
    title: str,
    description: str,
    privacy: str = "private",
    client_secrets_path: Path = Path("credentials.json"),
    token_path: Path = Path("youtube-token.json"),
    youtube_service: Any | None = None,
    made_for_kids: bool = False,
    expected_channel_id: str | None = None,
) -> tuple[str, str]:
    """Upload a video with resumable MediaFileUpload and return ID and URL."""
    if not video_path.is_file():
        raise YouTubeUploadError(f"Fichier video introuvable : {video_path}")
    if privacy not in {"private", "unlisted", "public"}:
        raise YouTubeUploadError("La visibilite doit etre private, unlisted ou public.")

    _, _, _, _, HttpError, MediaFileUpload = _load_google_dependencies()
    try:
        service = youtube_service or authenticate_youtube(
            client_secrets_path, token_path, expected_channel_id
        )
        verify_expected_channel(service, expected_channel_id)
        body = {
            "snippet": {"title": title, "description": description, "categoryId": "20"},
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": made_for_kids,
            },
        }
        media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
        request = service.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )
        response = None
        while response is None:
            _, response = request.next_chunk()
        video_id = response.get("id") if isinstance(response, dict) else None
        if not video_id:
            raise YouTubeUploadError("La reponse YouTube ne contient pas d'identifiant.")
        return video_id, f"https://www.youtube.com/watch?v={video_id}"
    except YouTubeUploadError:
        raise
    except HttpError as error:
        raise YouTubeUploadError(f"Echec de l'upload YouTube : {error}") from error
    except Exception as error:
        raise YouTubeUploadError(f"Echec de l'upload YouTube : {error}") from error
