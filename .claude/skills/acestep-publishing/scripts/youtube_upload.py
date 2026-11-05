#!/usr/bin/env python3
"""Upload a rendered music video to YouTube.

Ported from anime-short-generator's youtube/auth.py + youtube/service.py, trimmed to
what a music upload needs. Two differences that matter:

  * it asks for youtube.readonly alongside youtube.upload, so --list-channels can show
    which channel the token actually points at. The upload scope alone is write-only:
    you cannot see the destination before committing to it.
  * containsSyntheticMedia is hard-coded True. The audio is model-generated, and
    YouTube requires that disclosure for synthetic music.

Credentials live in ACE-Step-1.5/.youtube/ (gitignored), NOT in anime-short-generator -
its token.json is in use by a daily cron and must not be touched.

Usage:
    python3 youtube_upload.py --list-channels
    python3 youtube_upload.py --video out.mp4 --title "Green Light" \
        --description-file desc.txt --tags "chill,indie pop" --privacy private --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

CRED_DIR = Path(__file__).resolve().parents[4] / ".youtube"
TOKEN_FILE = CRED_DIR / "token.json"
CLIENT_SECRET_FILE = CRED_DIR / "client_secret.json"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]
MUSIC_CATEGORY_ID = "10"


def _token_has_scopes() -> bool:
    if not TOKEN_FILE.exists():
        return False
    try:
        data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    except Exception:
        return False
    scopes = data.get("scopes") or data.get("scope") or []
    if isinstance(scopes, str):
        scopes = scopes.split()
    return set(SCOPES).issubset(set(scopes))


def _consent(flow, headless: bool, port: int):
    """Run the OAuth consent handshake on localhost:<port>.

    This is a hand-rolled replacement for flow.run_local_server(), which is too
    fragile for a headless box reached over an SSH port-forward. Two failures seen
    in practice, both fatal there and both handled here:

      * it raises MismatchingStateError and exits on the FIRST request that is not
        the expected callback, so a forwarder's health probe on the port kills the
        whole flow before the user has even clicked anything.
      * it binds the port once, so a socket not yet released by a previous attempt
        is an immediate OSError.

    On a headless box the browser is on the user's machine, so the caller must
    forward the port (ssh -L <port>:localhost:<port>) for the redirect to arrive.
    """
    flow.redirect_uri = f"http://localhost:{port}/"
    auth_url, state = flow.authorization_url(prompt="consent", access_type="offline")
    if not headless:
        import webbrowser

        webbrowser.open(auth_url, new=1, autoraise=True)
    print(f"Open this URL and authorize:\n\n{auth_url}\n", flush=True)

    got = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            q = parse_qs(urlparse(self.path).query)
            if "error" in q:
                self._reply(400, b"authorization denied")
            elif "code" not in q:
                self._reply(204, b"")
            elif q.get("state", [None])[0] != state:
                self._reply(400, b"stale state - reopen the current link")
            else:
                got["code"] = q["code"][0]
                self._reply(200, b"<h2>Authorized. You can close this tab.</h2>")

        def _reply(self, status, body):
            self.send_response(status)
            if body:
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def log_message(self, *args):
            pass

    srv = None
    for _ in range(20):
        try:
            srv = HTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            time.sleep(1)
    if srv is None:
        raise RuntimeError(f"could not bind 127.0.0.1:{port} - is something else on it?")

    with srv:
        while "code" not in got:
            srv.handle_request()

    flow.fetch_token(code=got["code"])
    return flow.credentials


def get_credentials(headless: bool, port: int):
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if _token_has_scopes():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        except Exception:
            creds = None

    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
            return creds
        except RefreshError:
            pass

    if not CLIENT_SECRET_FILE.exists():
        raise FileNotFoundError(
            f"{CLIENT_SECRET_FILE} not found. Copy an OAuth client secret there "
            "(Google Cloud Console > APIs & Services > Credentials)."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_FILE), SCOPES)
    creds = _consent(flow, headless, port)
    CRED_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    TOKEN_FILE.chmod(0o600)
    return creds


def build_client(headless: bool, port: int):
    from googleapiclient.discovery import build

    return build("youtube", "v3", credentials=get_credentials(headless, port))


def list_channels(youtube) -> None:
    resp = youtube.channels().list(part="snippet,statistics", mine=True).execute()
    items = resp.get("items", [])
    if not items:
        print("No channel is reachable with this token.")
        return
    for ch in items:
        snip = ch["snippet"]
        print(f"  id       : {ch['id']}")
        print(f"  title    : {snip['title']}")
        print(f"  handle   : {snip.get('customUrl', '(none)')}")
        print(f"  subs     : {ch['statistics'].get('subscriberCount', '?')}")
        print(f"  videos   : {ch['statistics'].get('videoCount', '?')}")


def upload(youtube, video: Path, title: str, description: str, tags: list[str],
           privacy: str, thumbnail: Path | None) -> str:
    from googleapiclient.http import MediaFileUpload

    snippet: dict[str, object] = {
        "title": title,
        "description": description,
        "categoryId": MUSIC_CATEGORY_ID,
    }
    if tags:
        snippet["tags"] = tags

    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": snippet,
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": False,
                "containsSyntheticMedia": True,
            },
        },
        media_body=MediaFileUpload(str(video), mimetype="video/mp4",
                                   resumable=True, chunksize=10 * 1024 * 1024),
        notifySubscribers=False,
    )

    response = None
    while response is None:
        progress, response = request.next_chunk()
        if progress:
            print(f"  uploading {int(progress.progress() * 100)}%", flush=True)

    video_id = response["id"]
    print(f"  done: https://youtu.be/{video_id}  ({privacy})")

    if thumbnail is not None:
        try:
            youtube.thumbnails().set(
                videoId=video_id, media_body=MediaFileUpload(str(thumbnail))
            ).execute()
            print(f"  thumbnail set from {thumbnail.name}")
        except Exception as exc:  # unverified channels cannot set custom thumbnails
            print(f"  thumbnail NOT set: {exc}", file=sys.stderr)

    return video_id


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list-channels", action="store_true",
                    help="print the channel this token uploads to, then exit")
    ap.add_argument("--video", type=Path)
    ap.add_argument("--title")
    ap.add_argument("--description", default="")
    ap.add_argument("--description-file", type=Path)
    ap.add_argument("--tags", default="", help="comma separated")
    ap.add_argument("--thumbnail", type=Path)
    ap.add_argument("--privacy", default="private",
                    choices=["private", "unlisted", "public"])
    ap.add_argument("--dry-run", action="store_true",
                    help="print exactly what would be sent, upload nothing")
    ap.add_argument("--headless", action="store_true",
                    help="do not try to open a browser during OAuth")
    ap.add_argument("--oauth-port", type=int, default=8080)
    args = ap.parse_args()

    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    description = args.description
    if args.description_file:
        description = args.description_file.read_text(encoding="utf-8")

    if args.dry_run:
        if not args.video or not args.title:
            ap.error("--video and --title are required")
        print(json.dumps({
            "video": str(args.video),
            "size_mb": round(args.video.stat().st_size / 1e6, 1) if args.video.exists() else None,
            "exists": args.video.exists(),
            "thumbnail": str(args.thumbnail) if args.thumbnail else None,
            "snippet": {"title": args.title, "description": description,
                        "tags": tags, "categoryId": MUSIC_CATEGORY_ID},
            "status": {"privacyStatus": args.privacy,
                       "selfDeclaredMadeForKids": False,
                       "containsSyntheticMedia": True},
        }, indent=2, ensure_ascii=False))
        return 0

    youtube = build_client(args.headless, args.oauth_port)

    if args.list_channels:
        list_channels(youtube)
        return 0

    if not args.video or not args.title:
        ap.error("--video and --title are required")
    if not args.video.exists():
        ap.error(f"not found: {args.video}")

    print("Uploading to:")
    list_channels(youtube)
    upload(youtube, args.video, args.title, description, tags, args.privacy, args.thumbnail)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
