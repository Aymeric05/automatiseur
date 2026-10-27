"""The PeakMoments TikTok account: each Short published on YouTube is sent there as a draft.

Content Posting API, "upload to inbox" (scope video.upload): the video lands in
the account's TikTok inbox; the owner opens it in the TikTok app, can add a
trending sound and edit the caption, then posts it. Nothing is posted without them.

The account is authorized once (``authorize``, Login Kit for Desktop: the
browser comes back to ``REDIRECT_URI`` on this computer); the tokens are kept
in ``TOKEN_PATH``-like files and refreshed when needed (the access token lasts a
day, the refresh token a year).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import secrets
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
USER_INFO_URL = "https://open.tiktokapis.com/v2/user/info/?fields=open_id,display_name,avatar_url"
INBOX_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
REDIRECT_PORT = 8765
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback/"
SCOPES = "user.info.basic,video.upload"
SINGLE_CHUNK_LIMIT = 64 * 1024 * 1024  # up to this size a video goes in one piece
CHUNK_SIZE = 10 * 1024 * 1024  # otherwise in 10 MB pieces (the last one takes the rest)


class TikTokError(RuntimeError):
    """Raised when TikTok refuses a request."""


def authorize(client_key: str, client_secret: str, token_path: Path) -> str:
    """Open TikTok's consent page, catch the answer on this computer, keep the tokens."""
    verifier = secrets.token_urlsafe(48)
    state = secrets.token_urlsafe(16)
    url = AUTHORIZE_URL + "?" + urllib.parse.urlencode({
        "client_key": client_key, "scope": SCOPES, "response_type": "code", "redirect_uri": REDIRECT_URI,
        "state": state, "code_challenge": hashlib.sha256(verifier.encode()).hexdigest(),  # TikTok: hex digest
        "code_challenge_method": "S256",
    })
    answer: dict[str, str] = {}

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (http.server's name)
            answer.update({k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            done = "code" in answer and answer.get("state") == state
            self.wfile.write(("<h1>Automatiseur</h1><p>" + (
                "Compte TikTok autorise. Vous pouvez fermer cette page." if done
                else "Autorisation refusee ou interrompue.") + "</p>").encode())

        def log_message(self, *args: Any) -> None:
            pass

    with HTTPServer(("localhost", REDIRECT_PORT), Callback) as server:
        server.timeout = 300
        webbrowser.open(url)
        print(f"Autorisez le compte TikTok dans le navigateur (sinon ouvrez : {url})")
        while not answer:
            server.handle_request()
    if answer.get("state") != state or "code" not in answer:
        raise TikTokError(f"Autorisation TikTok refusee : {answer.get('error_description') or answer.get('error') or answer}")
    tokens = _token_request({
        "client_key": client_key, "client_secret": client_secret, "code": answer["code"],
        "grant_type": "authorization_code", "redirect_uri": REDIRECT_URI, "code_verifier": verifier,
    })
    _save(token_path, tokens)
    return str(tokens.get("open_id", ""))


def access_token(client_key: str, client_secret: str, token_path: Path) -> str:
    """A valid access token, refreshed when it is about to expire."""
    try:
        tokens = json.loads(token_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TikTokError("Compte TikTok pas encore autorise (--authorize-tiktok).") from error
    if datetime.fromisoformat(tokens["expires_at"]) - timedelta(minutes=5) > datetime.now(timezone.utc):
        return tokens["access_token"]
    tokens = _token_request({
        "client_key": client_key, "client_secret": client_secret,
        "grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
    })
    _save(token_path, tokens)
    return tokens["access_token"]


def display_name(token: str) -> str:
    """The connected account's display name (scope user.info.basic), to show which one is linked."""
    request = urllib.request.Request(USER_INFO_URL, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            user = (json.load(response).get("data") or {}).get("user") or {}
    except urllib.error.HTTPError as error:
        raise TikTokError(f"Compte TikTok illisible : {error.read().decode(errors='replace')[:300]}") from error
    return str(user.get("display_name") or "")


def upload_draft(video: Path, token: str) -> str:
    """Send ``video`` to the account's TikTok inbox as a draft; returns TikTok's publish id."""
    size = video.stat().st_size
    chunk = size if size <= SINGLE_CHUNK_LIMIT else CHUNK_SIZE
    count = max(1, size // chunk)
    init = _json_request(INBOX_INIT_URL, token, {"source_info": {
        "source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": count,
    }})
    data = init.get("data") or {}
    with video.open("rb") as file:
        for index in range(count):
            start = index * chunk
            end = size - 1 if index == count - 1 else start + chunk - 1  # the last piece takes the rest
            file.seek(start)
            request = urllib.request.Request(data["upload_url"], data=file.read(end - start + 1), method="PUT", headers={
                "Content-Type": "video/mp4", "Content-Range": f"bytes {start}-{end}/{size}",
            })
            with urllib.request.urlopen(request, timeout=300):
                pass
    return str(data.get("publish_id", ""))


def _json_request(url: str, token: str, body: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8",
    })
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            answer = json.load(response)
    except urllib.error.HTTPError as error:
        raise TikTokError(f"TikTok refuse l'envoi : {error.read().decode(errors='replace')[:300]}") from error
    if (answer.get("error") or {}).get("code", "ok") != "ok":
        raise TikTokError(f"TikTok refuse l'envoi : {answer['error']}")
    return answer


def _token_request(form: dict[str, str]) -> dict[str, Any]:
    request = urllib.request.Request(TOKEN_URL, data=urllib.parse.urlencode(form).encode(), method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded",
    })
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            tokens = json.load(response)
    except urllib.error.HTTPError as error:
        raise TikTokError(f"Jeton TikTok refuse : {error.read().decode(errors='replace')[:300]}") from error
    if "access_token" not in tokens:
        raise TikTokError(f"Jeton TikTok refuse : {tokens.get('error_description') or tokens}")
    return tokens


def _save(path: Path, tokens: dict[str, Any]) -> None:
    tokens = {**tokens, "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=int(tokens.get("expires_in", 0)))).isoformat()}
    path.write_text(json.dumps(tokens), encoding="utf-8")
