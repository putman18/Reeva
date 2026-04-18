"""
clip_uploader.py

Uploads processed vertical clips to:
  - YouTube Shorts (via YouTube Data API v3 - Google creds already in .env)
  - X / Twitter (via Twitter API v2 - needs API keys in .env)

TikTok has no reliable API for personal accounts - handled manually or via Buffer.

Setup needed (one-time):
  YouTube: Google credentials already configured (GOOGLE_CREDENTIALS_FILE in .env)
  X/Twitter: Add to .env:
    TWITTER_API_KEY=...
    TWITTER_API_SECRET=...
    TWITTER_ACCESS_TOKEN=...
    TWITTER_ACCESS_TOKEN_SECRET=...
    (Register free at developer.twitter.com)

Usage:
    python clipping/execution/clip_uploader.py --clip clip.mp4 --title "insane clutch" --platforms youtube,twitter
    python clipping/execution/clip_uploader.py --clip clip.mp4 --title "insane play" --platforms youtube
"""

import argparse
import os
import time
import json
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")


# ─── YouTube ──────────────────────────────────────────────────────────────────

def upload_youtube(clip_path: Path, title: str, description: str = "", tags: list = None) -> str | None:
    """Upload clip as a YouTube Short. Returns video URL or None on failure."""
    try:
        import google.oauth2.credentials
        import google_auth_oauthlib.flow
        import googleapiclient.discovery
        import googleapiclient.http
    except ImportError:
        print("Google API packages not installed. Run: pip install google-api-python-client google-auth-oauthlib")
        return None

    creds_file  = os.getenv("GOOGLE_CREDENTIALS_FILE")
    token_file  = os.getenv("GOOGLE_TOKEN_FILE")

    if not creds_file:
        print("GOOGLE_CREDENTIALS_FILE not set in .env")
        return None

    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

    # Load or refresh credentials
    creds = None
    if token_file and Path(token_file).exists():
        import google.oauth2.credentials
        import json
        token_data = json.loads(Path(token_file).read_text())
        creds = google.oauth2.credentials.Credentials.from_authorized_user_info(token_data, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
        else:
            flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(creds_file, SCOPES)
            creds = flow.run_local_server(port=0)
        if token_file:
            Path(token_file).write_text(creds.to_json())

    youtube = googleapiclient.discovery.build("youtube", "v3", credentials=creds)

    # #Shorts in title + description signals YouTube to show as Short
    short_title = f"{title} #Shorts"
    short_desc  = f"{description}\n\n#Shorts #Gaming #Clips"

    body = {
        "snippet": {
            "title":       short_title[:100],
            "description": short_desc[:5000],
            "tags":        (tags or []) + ["Shorts", "Gaming", "Clips"],
            "categoryId":  "20",  # Gaming
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        }
    }

    media = googleapiclient.http.MediaFileUpload(
        str(clip_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=1024 * 1024 * 5  # 5MB chunks
    )

    print(f"  Uploading to YouTube Shorts: {clip_path.name}")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            print(f"  Upload progress: {pct}%", end="\r")

    video_id = response["id"]
    url = f"https://www.youtube.com/shorts/{video_id}"
    print(f"  YouTube: {url}")
    return url


# ─── X / Twitter ──────────────────────────────────────────────────────────────

def upload_twitter(clip_path: Path, caption: str) -> str | None:
    """Upload clip to X (Twitter). Returns tweet URL or None on failure."""
    try:
        import requests
        from requests_oauthlib import OAuth1
    except ImportError:
        print("requests-oauthlib not installed. Run: pip install requests-oauthlib")
        return None

    api_key    = os.getenv("TWITTER_API_KEY")
    api_secret = os.getenv("TWITTER_API_SECRET")
    token      = os.getenv("TWITTER_ACCESS_TOKEN")
    token_secret = os.getenv("TWITTER_ACCESS_TOKEN_SECRET")

    if not all([api_key, api_secret, token, token_secret]):
        print("Twitter API keys missing from .env. Add TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET")
        return None

    auth = OAuth1(api_key, api_secret, token, token_secret)

    # Step 1: init upload
    file_size = clip_path.stat().st_size
    init_resp = requests.post(
        "https://upload.twitter.com/1.1/media/upload.json",
        data={
            "command": "INIT",
            "total_bytes": file_size,
            "media_type": "video/mp4",
            "media_category": "tweet_video",
        },
        auth=auth
    )
    if init_resp.status_code != 202:
        print(f"  Twitter upload INIT failed: {init_resp.text}")
        return None

    media_id = init_resp.json()["media_id_string"]

    # Step 2: append chunks (5MB)
    chunk_size = 5 * 1024 * 1024
    with open(clip_path, "rb") as f:
        segment_index = 0
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            requests.post(
                "https://upload.twitter.com/1.1/media/upload.json",
                data={"command": "APPEND", "media_id": media_id, "segment_index": segment_index},
                files={"media": chunk},
                auth=auth
            )
            segment_index += 1
            print(f"  Twitter upload: chunk {segment_index}", end="\r")

    # Step 3: finalize
    fin_resp = requests.post(
        "https://upload.twitter.com/1.1/media/upload.json",
        data={"command": "FINALIZE", "media_id": media_id},
        auth=auth
    )

    # Step 4: wait for processing
    processing_info = fin_resp.json().get("processing_info")
    if processing_info:
        state = processing_info.get("state")
        while state == "pending" or state == "in_progress":
            wait = processing_info.get("check_after_secs", 5)
            print(f"  Twitter processing ({state}), waiting {wait}s...")
            time.sleep(wait)
            check = requests.get(
                "https://upload.twitter.com/1.1/media/upload.json",
                params={"command": "STATUS", "media_id": media_id},
                auth=auth
            )
            processing_info = check.json().get("processing_info", {})
            state = processing_info.get("state", "succeeded")

    # Step 5: post tweet
    tweet_resp = requests.post(
        "https://api.twitter.com/2/tweets",
        json={"text": caption[:280], "media": {"media_ids": [media_id]}},
        auth=auth,
        headers={"Content-Type": "application/json"}
    )

    if tweet_resp.status_code != 201:
        print(f"  Tweet post failed: {tweet_resp.text}")
        return None

    tweet_id = tweet_resp.json()["data"]["id"]
    # Need username for URL - use a placeholder; tracker will store the ID
    url = f"https://x.com/i/status/{tweet_id}"
    print(f"  X (Twitter): {url}")
    return url


# ─── Main ─────────────────────────────────────────────────────────────────────

def upload(
    clip_path: Path,
    title: str,
    description: str = "",
    tags: list = None,
    platforms: list = None,
) -> dict:
    """Upload to specified platforms. Returns dict of {platform: url}."""
    if platforms is None:
        platforms = ["youtube"]

    results = {}

    if "youtube" in platforms:
        url = upload_youtube(clip_path, title, description, tags)
        if url:
            results["youtube"] = url

    if "twitter" in platforms or "x" in platforms:
        caption = f"{title} #Gaming #Clips"
        url = upload_twitter(clip_path, caption)
        if url:
            results["twitter"] = url

    return results


def main():
    parser = argparse.ArgumentParser(description="Upload a clip to YouTube Shorts and/or X")
    parser.add_argument("--clip",      required=True, help="Path to processed clip (.mp4)")
    parser.add_argument("--title",     required=True, help="Title / caption for the clip")
    parser.add_argument("--desc",      default="",    help="Optional description")
    parser.add_argument("--tags",      default="",    help="Comma-separated tags")
    parser.add_argument("--platforms", default="youtube", help="Platforms: youtube,twitter (comma-separated)")
    args = parser.parse_args()

    clip_path = Path(args.clip)
    if not clip_path.exists():
        print(f"File not found: {clip_path}")
        return

    tags      = [t.strip() for t in args.tags.split(",") if t.strip()]
    platforms = [p.strip().lower() for p in args.platforms.split(",")]

    print(f"Uploading: {clip_path.name}")
    print(f"Platforms: {platforms}")

    results = upload(clip_path, args.title, args.desc, tags, platforms)

    print(f"\nUploaded to {len(results)} platform(s):")
    for platform, url in results.items():
        print(f"  {platform}: {url}")


if __name__ == "__main__":
    main()
