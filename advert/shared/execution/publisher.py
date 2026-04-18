"""
publisher.py

Publishes markdown articles to Ghost CMS via the Admin API.
Reads articles from .tmp/articles/<niche>/ and posts them.

Usage:
    python shared/execution/publisher.py --file .tmp/articles/finance/best-credit-cards-for-beginners.md
    python shared/execution/publisher.py --batch .tmp/articles/finance/ --limit 5
    python shared/execution/publisher.py --batch .tmp/articles/finance/ --all
"""

import argparse
import hashlib
import hmac
import json
import os
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import jwt

ADVERT_ROOT  = Path(__file__).parent.parent.parent
PROJECT_ROOT = ADVERT_ROOT.parent

env_file = PROJECT_ROOT / ".env"
for line in env_file.read_text().splitlines() if env_file.exists() else []:
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

TMP_DIR = PROJECT_ROOT / ".tmp"

GHOST_URL     = os.getenv("GHOST_URL", "http://187.124.250.181:2368")
GHOST_API_KEY = os.getenv("GHOST_ADMIN_API_KEY", "")


# ---------------------------------------------------------------------------
# Ghost Admin API auth (JWT)
# ---------------------------------------------------------------------------

def ghost_token() -> str:
    """Generate a short-lived JWT for Ghost Admin API."""
    key_id, secret = GHOST_API_KEY.split(":")
    iat = int(datetime.now(timezone.utc).timestamp())
    payload = {
        "iat": iat,
        "exp": iat + 300,  # 5 minute expiry
        "aud": "/admin/",
    }
    token = jwt.encode(payload, bytes.fromhex(secret), algorithm="HS256", headers={"kid": key_id})
    return token


def ghost_post(endpoint: str, payload: dict) -> dict:
    """POST to Ghost Admin API."""
    token = ghost_token()
    url = f"{GHOST_URL}/ghost/api/admin/{endpoint}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Authorization": f"Ghost {token}",
            "Content-Type": "application/json",
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


# ---------------------------------------------------------------------------
# Markdown parser
# ---------------------------------------------------------------------------

def parse_article(path: Path) -> dict:
    """Parse a generated markdown file into title + content + meta."""
    text = path.read_text(encoding="utf-8")

    # Strip frontmatter
    meta = {}
    if text.startswith("---"):
        end = text.index("---", 3)
        frontmatter = text[3:end].strip()
        text = text[end+3:].strip()
        for line in frontmatter.splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                meta[k.strip()] = v.strip()

    # Extract title from first H1
    lines = text.splitlines()
    title = meta.get("title", path.stem.replace("-", " ").title())
    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip()
            break

    # Remove meta description line (in brackets on line after title)
    clean_lines = []
    skip_next = False
    for line in lines:
        if skip_next and line.startswith("[") and line.endswith("]"):
            skip_next = False
            continue
        if line.startswith("# "):
            skip_next = True
        clean_lines.append(line)

    content = "\n".join(clean_lines).strip()

    return {
        "title":    title,
        "content":  content,
        "slug":     re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-"),
        "meta_description": meta.get("meta", ""),
        "keyword":  meta.get("keyword", ""),
        "niche":    meta.get("niche", ""),
    }


# ---------------------------------------------------------------------------
# Publish to Ghost
# ---------------------------------------------------------------------------

def publish_article(article: dict, status: str = "published") -> str:
    """Publish a single article to Ghost. Returns the published URL."""
    payload = {
        "posts": [{
            "title":            article["title"],
            "slug":             article["slug"],
            "mobiledoc":        mobiledoc_from_markdown(article["content"]),
            "status":           status,
            "meta_description": article["meta_description"],
            "tags":             [{"name": article["niche"].title()}],
        }]
    }

    result = ghost_post("posts/", payload)
    post = result["posts"][0]
    return post.get("url", f"{GHOST_URL}/{post['slug']}/")


def mobiledoc_from_markdown(markdown: str) -> str:
    """
    Wrap markdown in a Ghost mobiledoc markdown card.
    Ghost renders markdown cards natively.
    """
    doc = {
        "version": "0.3.1",
        "markups": [],
        "atoms": [],
        "cards": [["markdown", {"markdown": markdown}]],
        "sections": [[10, 0]],
    }
    return json.dumps(doc)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_single(file_path: str, status: str = "published"):
    path = Path(file_path)
    if not path.exists():
        print(f"File not found: {file_path}")
        return

    article = parse_article(path)
    print(f"Publishing: {article['title']}")
    url = publish_article(article, status)
    print(f"Live at: {url}")

    # Mark file as published
    text = path.read_text(encoding="utf-8")
    text = text.replace("status: draft", "status: published")
    path.write_text(text, encoding="utf-8")


def run_batch(folder: str, limit: int, status: str = "published"):
    folder_path = Path(folder)
    if not folder_path.exists():
        print(f"Folder not found: {folder}")
        return

    # Only unpublished drafts
    files = [
        f for f in sorted(folder_path.glob("*.md"))
        if "status: draft" in f.read_text(encoding="utf-8")
    ]

    if limit > 0:
        files = files[:limit]

    print(f"\nPublishing {len(files)} articles from {folder}")
    print("-" * 50)

    for i, path in enumerate(files):
        article = parse_article(path)
        print(f"[{i+1}/{len(files)}] {article['title']}")
        try:
            url = publish_article(article, status)
            print(f"  Live: {url}")

            text = path.read_text(encoding="utf-8")
            text = text.replace("status: draft", "status: published")
            path.write_text(text, encoding="utf-8")

        except Exception as e:
            print(f"  ERROR: {e}")

        if i < len(files) - 1:
            time.sleep(1)

    print(f"\nDone.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file",   help="Single article markdown file to publish")
    parser.add_argument("--batch",  help="Folder of articles to publish")
    parser.add_argument("--limit",  type=int, default=5, help="Max articles in batch (0 = all)")
    parser.add_argument("--draft",  action="store_true", help="Publish as draft instead of live")
    args = parser.parse_args()

    status = "draft" if args.draft else "published"

    if args.file:
        run_single(args.file, status)
    elif args.batch:
        run_batch(args.batch, args.limit, status)
    else:
        print("Provide --file or --batch")
