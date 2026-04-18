"""
shortform_writer.py

Generates short-form social content from existing articles.
Produces LinkedIn posts, TikTok/Shorts scripts, and Twitter/X threads
from articles already published on the site.

Usage:
    python shared/execution/shortform_writer.py --article "how-to-build-wealth"
    python shared/execution/shortform_writer.py --batch 5   # pick 5 random articles
    python shared/execution/shortform_writer.py --all       # generate for all articles

Output: .tmp/shortform/<slug>/linkedin.txt, tiktok_script.txt, twitter_thread.txt
"""

import argparse
import os
import random
from datetime import datetime
from pathlib import Path

ADVERT_ROOT  = Path(__file__).parent.parent.parent
PROJECT_ROOT = ADVERT_ROOT.parent

env_file = PROJECT_ROOT / ".env"
for line in env_file.read_text().splitlines() if env_file.exists() else []:
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

TMP_DIR      = PROJECT_ROOT / ".tmp"
ARTICLES_DIR = TMP_DIR / "articles" / "finance"
OUTPUT_DIR   = TMP_DIR / "shortform"
OUTPUT_DIR.mkdir(exist_ok=True)


def get_article_body(path: Path) -> tuple[str, str, str]:
    text = path.read_text(encoding="utf-8")
    meta = {}
    body = text
    if text.startswith("---"):
        end = text.index("---", 3)
        for line in text[3:end].strip().splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                meta[k.strip()] = v.strip()
        body = text[end+3:].strip()
    keyword = meta.get("keyword", path.stem.replace("-", " "))
    title_line = ""
    for line in body.splitlines():
        if line.startswith("# "):
            title_line = line[2:].strip()
            break
    return keyword, title_line, body


def generate_shortform(keyword: str, title: str, body: str, client) -> dict:
    from google.genai import types

    # Truncate body to save tokens
    body_short = " ".join(body.split()[:800])

    prompt = f"""You are a social media content writer for The Finance Blueprint, a personal finance site by Jordan Hale.

Based on this article about "{keyword}", generate 3 pieces of short-form content.

Article title: {title}
Article excerpt: {body_short}

Generate exactly these 3 formats, separated by "---FORMAT---":

FORMAT 1: LINKEDIN POST
- 150-200 words max
- Start with a bold hook line (no hashtag, no emoji)
- Share 3-5 key insights from the article as a list
- End with: "Full guide at thefinanceblueprint.com (link in comments)"
- Add 3 hashtags at the bottom: #PersonalFinance #MoneyTips and one topic-specific tag
- No em dashes anywhere

---FORMAT---

FORMAT 2: TIKTOK/SHORTS SCRIPT
- 45-60 seconds when spoken (about 120-140 words)
- Hook: first 3 seconds must be attention-grabbing ("Did you know...", "Stop doing this...", "Here's why...")
- Conversational, energetic tone
- 3-4 main points spoken naturally
- End with: "Follow for more money tips"
- Include [PAUSE] markers where the speaker should pause
- No em dashes anywhere

---FORMAT---

FORMAT 3: TWITTER/X THREAD
- 5 tweets, each under 280 characters
- Tweet 1: Hook that makes people want to read more (end with "Thread:")
- Tweets 2-4: One key insight per tweet, numbered (2/, 3/, 4/)
- Tweet 5: Summary + "Full guide: thefinanceblueprint.com"
- No em dashes anywhere

Output only the 3 formats separated by ---FORMAT---. No preamble."""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            max_output_tokens=2000,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    content = response.text
    parts   = content.split("---FORMAT---")

    return {
        "linkedin": parts[0].strip() if len(parts) > 0 else "",
        "tiktok":   parts[1].strip() if len(parts) > 1 else "",
        "twitter":  parts[2].strip() if len(parts) > 2 else "",
    }


def save_shortform(slug: str, content: dict, keyword: str):
    out_dir = OUTPUT_DIR / slug
    out_dir.mkdir(exist_ok=True)

    header = f"# Short-form content for: {keyword}\n# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"

    (out_dir / "linkedin.txt").write_text(header + content["linkedin"], encoding="utf-8")
    (out_dir / "tiktok_script.txt").write_text(header + content["tiktok"], encoding="utf-8")
    (out_dir / "twitter_thread.txt").write_text(header + content["twitter"], encoding="utf-8")

    print(f"  Saved to .tmp/shortform/{slug}/")


def process_article(path: Path, client) -> bool:
    slug    = path.stem
    keyword, title, body = get_article_body(path)
    print(f"  Generating for: {keyword}")
    try:
        content = generate_shortform(keyword, title, body, client)
        save_shortform(slug, content, keyword)
        return True
    except Exception as e:
        print(f"  ERROR: {e}")
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--article", help="Specific article slug (e.g. how-to-build-wealth)")
    parser.add_argument("--batch",   type=int, help="Generate for N random articles")
    parser.add_argument("--all",     action="store_true", help="Generate for all articles")
    args = parser.parse_args()

    from google import genai
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not set in .env")
    client = genai.Client(api_key=api_key)

    md_files = list(ARTICLES_DIR.glob("*.md"))
    if not md_files:
        print("No articles found.")
        return

    targets = []
    if args.article:
        match = [f for f in md_files if f.stem == args.article]
        if not match:
            print(f"Article '{args.article}' not found.")
            return
        targets = match
    elif args.batch:
        targets = random.sample(md_files, min(args.batch, len(md_files)))
    elif args.all:
        targets = md_files
    else:
        parser.print_help()
        return

    print(f"Generating short-form content for {len(targets)} articles\n" + "-" * 50)
    ok = sum(1 for t in targets if process_article(t, client))
    print(f"\nDone: {ok}/{len(targets)} articles processed")
    print(f"Output: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
