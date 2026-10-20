"""YouTube Shorts upload helpers using the official Google APIs."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
YOUTUBE_SCOPES = [YOUTUBE_UPLOAD_SCOPE, YOUTUBE_READONLY_SCOPE]
# Retention (average share of each Short watched): its own token, so the upload
# authorization never changes and nothing waits for a new sign-in.
YOUTUBE_ANALYTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"
ANALYTICS_TOKEN_NAME = "youtube-analytics-token.json"
UPLOAD_CHUNK_BYTES = 4 * 1024 * 1024
UPLOAD_RETRIES = 5  # network errors and timeouts, with growing pauses
# Rejections that mean a rights or rules problem (not "duplicate" or "length").
WARNING_REASONS = frozenset({"copyright", "legal", "trademark", "termsOfUse", "inappropriate"})


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
    allow_browser: bool = True,
):
    """Load or create local OAuth credentials for YouTube uploads.

    When the saved authorization is missing, insufficient or no longer
    accepted by Google (e.g. expired after 7 days while the Google Cloud app
    is in "Testing" mode), the Google sign-in page is opened, unless
    ``allow_browser`` is False: unattended uploads then fail with a clear
    message instead of waiting for someone in front of a browser.
    """
    _, _, _, build, _, _ = _load_google_dependencies()
    scopes = [YOUTUBE_UPLOAD_SCOPE]
    if expected_channel_id:
        scopes.append(YOUTUBE_READONLY_SCOPE)
    try:
        credentials = _credentials(
            client_secrets_path, token_path, scopes, allow_browser,
            "Autorisation YouTube expiree ou absente : relancez la surveillance avec "
            "--auto-upload-youtube (ou un upload manuel) pour vous reconnecter.",
        )
        return build("youtube", "v3", credentials=credentials)
    except YouTubeUploadError:
        raise
    except Exception as error:
        raise YouTubeUploadError(f"Echec de l'authentification YouTube : {error}") from error


def _credentials(
    client_secrets_path: Path, token_path: Path, scopes: list[str], allow_browser: bool, missing: str
):
    """Saved OAuth credentials with ``scopes``, refreshed, or a new sign-in when allowed."""
    Request, Credentials, InstalledAppFlow, _, _, _ = _load_google_dependencies()
    from google.auth.exceptions import RefreshError
    credentials = None
    if token_path.is_file():
        # No scopes argument: it would replace the scopes the token was granted.
        credentials = Credentials.from_authorized_user_file(str(token_path))
        if not credentials.scopes or not set(scopes).issubset(credentials.scopes):
            credentials = None
    if credentials is None or not credentials.valid:
        if credentials is not None and credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(Request())
            except RefreshError:
                credentials = None  # revoked or expired: a new sign-in is needed
        if credentials is None or not credentials.valid:
            if not allow_browser:
                raise YouTubeUploadError(missing)
            if not client_secrets_path.is_file():
                raise YouTubeUploadError(
                    f"Fichier OAuth introuvable : {client_secrets_path}"
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(client_secrets_path), scopes
            )
            # 127.0.0.1, not "localhost": a browser resolving localhost to IPv6 never
            # reaches the local server and the sign-in hangs.
            credentials = flow.run_local_server(host="127.0.0.1", port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(credentials.to_json(), encoding="utf-8")
    return credentials


def authorize_youtube_analytics(client_secrets_path: Path, token_path: Path) -> None:
    """One-time sign-in (browser) allowing the app to read the Shorts' retention."""
    _credentials(client_secrets_path, token_path, [YOUTUBE_ANALYTICS_SCOPE], True, "")


def authorize_channel(
    client_secrets_path: Path, token_path: Path, analytics_token_path: Path, other_channel_id: str | None
) -> tuple[str, str]:
    """One-time sign-in (browser) allowing the app to publish on a second channel.

    The channel picked in Google's account chooser must not be ``other_channel_id``
    (the first one). Returns its id and title; one token serves uploads and retention.
    """
    _, _, _, build, _, _ = _load_google_dependencies()
    scopes = [YOUTUBE_UPLOAD_SCOPE, YOUTUBE_READONLY_SCOPE, YOUTUBE_ANALYTICS_SCOPE]
    credentials = _credentials(client_secrets_path, token_path, scopes, True, "")
    response = build("youtube", "v3", credentials=credentials).channels().list(part="snippet", mine=True).execute(num_retries=UPLOAD_RETRIES)
    channel = (response.get("items") or [{}])[0]
    if not channel.get("id") or channel["id"] == other_channel_id:
        token_path.unlink(missing_ok=True)
        raise YouTubeUploadError(
            "Ce n'est pas la nouvelle chaine : relancez et choisissez-la dans la liste des comptes Google."
        )
    analytics_token_path.write_text(token_path.read_text(encoding="utf-8"), encoding="utf-8")
    return channel["id"], channel.get("snippet", {}).get("title", "")


def find_uploaded_video(
    title: str, client_secrets_path: Path, token_path: Path, expected_channel_id: str | None = None,
) -> tuple[str, str] | None:
    """The channel's recent upload with exactly this title, or None (3 API quota units).

    An upload cut by a network drop can still reach YouTube without the app getting
    the confirmation: before sending it again, the app looks for it here.
    """
    service = authenticate_youtube(client_secrets_path, token_path, expected_channel_id or "check", allow_browser=False)
    channels = service.channels().list(part="contentDetails", mine=True).execute(num_retries=UPLOAD_RETRIES)
    playlist = channels["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    items = service.playlistItems().list(
        part="snippet", playlistId=playlist, maxResults=50
    ).execute(num_retries=UPLOAD_RETRIES).get("items", [])
    for item in items:
        if item["snippet"].get("title") == title:
            video_id = item["snippet"]["resourceId"]["videoId"]
            return video_id, f"https://www.youtube.com/watch?v={video_id}"
    return None


def fetch_video_retention(
    video_ids: list[str],
    start_date: str,
    client_secrets_path: Path = Path("credentials.json"),
    token_path: Path = Path(ANALYTICS_TOKEN_NAME),
) -> dict[str, dict[str, float]]:
    """Share watched, average seconds watched and engaged views of these videos (YouTube Analytics).

    Needs ``authorize_youtube_analytics`` once; never opens a browser.
    """
    try:
        _, _, _, build, _, _ = _load_google_dependencies()
        credentials = _credentials(
            client_secrets_path, token_path, [YOUTUBE_ANALYTICS_SCOPE], False,
            "Retention non autorisee : lancez une fois --authorize-youtube-analytics.",
        )
        service = build("youtubeAnalytics", "v2", credentials=credentials)
        today = date.today().isoformat()
        retention: dict[str, dict[str, float]] = {}
        for index in range(0, len(video_ids), 200):  # at most 200 rows per report
            response = service.reports().query(
                ids="channel==MINE", startDate=start_date, endDate=today, dimensions="video",
                metrics="engagedViews,averageViewDuration,averageViewPercentage",
                filters="video==" + ",".join(video_ids[index:index + 200]),
                sort="-engagedViews", maxResults=200,
            ).execute(num_retries=UPLOAD_RETRIES)
            for video_id, engaged, seconds, percent in response.get("rows", []):
                retention[video_id] = {
                    "engaged_views": int(engaged),
                    "avg_view_seconds": round(float(seconds), 1),
                    "retention_pct": round(float(percent), 1),
                }
        return retention
    except YouTubeUploadError:
        raise
    except Exception as error:
        raise YouTubeUploadError(f"Retention YouTube indisponible : {error}") from error


def get_authenticated_channel_id(youtube_service: Any) -> str:
    """Return the channel ID belonging to the OAuth-authorized account."""
    try:
        response = youtube_service.channels().list(
            part="id,snippet", mine=True
        ).execute(num_retries=UPLOAD_RETRIES)
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


def fetch_video_statistics(
    video_ids: list[str],
    client_secrets_path: Path = Path("credentials.json"),
    token_path: Path = Path("youtube-token.json"),
) -> dict[str, dict[str, int]]:
    """Views, likes and comments of these videos (1 API quota unit per 50 videos).

    ``problem`` tells when YouTube rejected a video (copyright, legal...) or
    blocks it in some countries (a claim); a removed video is simply missing.
    """
    try:
        service = authenticate_youtube(client_secrets_path, token_path, allow_browser=False)
        statistics: dict[str, dict[str, int]] = {}
        for index in range(0, len(video_ids), 50):
            response = service.videos().list(
                part="statistics,status,contentDetails", id=",".join(video_ids[index:index + 50])
            ).execute(num_retries=UPLOAD_RETRIES)
            for item in response.get("items", []):
                values = item.get("statistics", {})
                statistics[item["id"]] = {
                    "views": int(values.get("viewCount", 0)),
                    "likes": int(values.get("likeCount", 0)),
                    "comments": int(values.get("commentCount", 0)),
                }
                status = item.get("status", {})
                blocked = (item.get("contentDetails", {}).get("regionRestriction") or {}).get("blocked")
                if status.get("uploadStatus") == "rejected" and status.get("rejectionReason") in WARNING_REASONS:
                    statistics[item["id"]]["problem"] = f"rejete ({status['rejectionReason']})"
                elif blocked:
                    statistics[item["id"]]["problem"] = f"bloque dans {len(blocked)} pays"
        return statistics
    except YouTubeUploadError:
        raise
    except Exception as error:
        raise YouTubeUploadError(f"Statistiques YouTube indisponibles : {error}") from error


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
    allow_browser: bool = True,
) -> tuple[str, str]:
    """Upload a video with resumable MediaFileUpload and return ID and URL."""
    if not video_path.is_file():
        raise YouTubeUploadError(f"Fichier video introuvable : {video_path}")
    if privacy not in {"private", "unlisted", "public"}:
        raise YouTubeUploadError("La visibilite doit etre private, unlisted ou public.")

    _, _, _, _, HttpError, MediaFileUpload = _load_google_dependencies()
    try:
        service = youtube_service or authenticate_youtube(
            client_secrets_path, token_path, expected_channel_id, allow_browser=allow_browser
        )
        verify_expected_channel(service, expected_channel_id)
        body = {
            "snippet": {"title": title, "description": description, "categoryId": "20"},
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": made_for_kids,
            },
        }
        # Small chunks, each retried: a Wi-Fi drop resends a few MB, not the whole Short.
        media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True, chunksize=UPLOAD_CHUNK_BYTES)
        request = service.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )
        response = None
        while response is None:
            _, response = request.next_chunk(num_retries=UPLOAD_RETRIES)
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
