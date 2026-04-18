"""
youtube_miner.py

Mines YouTube personal finance videos for content ideas, then generates
SEO articles based on the topics and key points covered in each video.

How it works:
  1. Takes a YouTube video URL (or a list of them)
  2. Pulls the video transcript using youtube-transcript-api
  3. Sends transcript to Gemini to extract topics and generate an article
  4. Saves the article to .tmp/articles/finance/

Usage:
    # Single video
    python shared/execution/youtube_miner.py --url "https://www.youtube.com/watch?v=VIDEO_ID"

    # Batch from a list of top creator videos
    python shared/execution/youtube_miner.py --top-creators --limit 10

    # From a text file with one URL per line
    python shared/execution/youtube_miner.py --file urls.txt --limit 5
"""

import argparse
import os
import re
import time
from datetime import datetime
from pathlib import Path

from google import genai
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound, VideoUnavailable

ADVERT_ROOT  = Path(__file__).parent.parent.parent
PROJECT_ROOT = ADVERT_ROOT.parent

env_file = PROJECT_ROOT / ".env"
for line in env_file.read_text().splitlines() if env_file.exists() else []:
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

TMP_DIR = PROJECT_ROOT / ".tmp"
TMP_DIR.mkdir(exist_ok=True)

DAILY_LIMIT = 1500
USAGE_FILE  = TMP_DIR / "gemini_usage.json"


# ---------------------------------------------------------------------------
# Top personal finance YouTube channels - curated list of proven video topics
# Format: (video_id, channel_name, topic_hint)
# These are high-performing videos from major finance creators
# ---------------------------------------------------------------------------

TOP_CREATOR_VIDEOS = [
    # Graham Stephan
    ("aJq2_dMhGsA", "Graham Stephan", "how to save money in your 20s"),
    ("p6yDzKCLskI", "Graham Stephan", "how to build wealth from nothing"),
    # Andrei Jikh
    ("cKa4WwkKe0c", "Andrei Jikh", "passive income investing"),
    # Humphrey Yang
    ("A1xkSkxuKHg", "Humphrey Yang", "money mistakes to avoid"),
    # Nischa
    ("Y7J8msrBCxw", "Nischa", "budgeting tips that actually work"),
    # Mark Tilbury
    ("b4dQnUAEFHo", "Mark Tilbury", "investing for beginners"),
    # Marko - WhiteBoard Finance
    ("H0mzLUULiUY", "WhiteBoard Finance", "index funds explained"),
    # Nate O'Brien
    ("zMbJkkiNhTY", "Nate O'Brien", "frugal living tips"),
    # Ryan Scribner
    ("3P8u-VJLIAo", "Ryan Scribner", "stock market for beginners"),
    # The Plain Bagel
    ("w9OMvLpGimA", "The Plain Bagel", "personal finance basics"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_usage() -> dict:
    import json
    today = datetime.now().strftime("%Y-%m-%d")
    if USAGE_FILE.exists():
        data = json.loads(USAGE_FILE.read_text())
        if data.get("date") == today:
            return data
    return {"date": today, "requests": 0}


def record_request():
    import json
    usage = get_usage()
    usage["requests"] += 1
    USAGE_FILE.write_text(json.dumps(usage))


def check_limit():
    usage = get_usage()
    if usage["requests"] >= DAILY_LIMIT:
        raise RuntimeError(f"Daily Gemini limit reached ({DAILY_LIMIT}/day). Try again tomorrow.")
    return DAILY_LIMIT - usage["requests"]


def extract_video_id(url: str) -> str:
    patterns = [
        r"v=([a-zA-Z0-9_-]{11})",
        r"youtu\.be/([a-zA-Z0-9_-]{11})",
        r"embed/([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    if len(url) == 11 and re.match(r"^[a-zA-Z0-9_-]+$", url):
        return url
    raise ValueError(f"Could not extract video ID from: {url}")


def get_transcript(video_id: str) -> str:
    try:
        api = YouTubeTranscriptApi()
        fetched = api.fetch(video_id, languages=["en", "en-US", "en-GB"])
        return " ".join(s.text for s in fetched)
    except TranscriptsDisabled:
        raise RuntimeError("This video has transcripts disabled.")
    except NoTranscriptFound:
        raise RuntimeError("No English transcript found for this video.")
    except VideoUnavailable:
        raise RuntimeError("Video is unavailable or has been deleted.")


def transcript_to_article(transcript: str, topic_hint: str, client) -> dict:
    check_limit()

    # Truncate transcript to ~6000 words to stay within context limits
    words = transcript.split()
    if len(words) > 6000:
        transcript = " ".join(words[:6000]) + "..."

    prompt = f"""You are an expert SEO content writer for The Finance Blueprint, a personal finance site for young adults written by Jordan Hale.

Below is a transcript from a popular personal finance YouTube video about: "{topic_hint}"

Your job is to:
1. Identify the main financial topic and key advice from the transcript
2. Write a complete, original SEO article based on those ideas - do NOT copy sentences from the transcript
3. The article should be written in Jordan Hale's voice: like a smart friend explaining money, practical and conversational
4. Target a specific SEO keyword that fits the topic naturally

ARTICLE REQUIREMENTS:
- Length: 1,800-2,000 words MAXIMUM. Hard cap. Cut anything that doesn't add direct value.
- Start with "# [Article Title]" on line 1
- Line 2: [meta description in square brackets, under 155 characters]
- Use H2 (##) subheadings throughout, avoid H3 unless essential
- Write in second person ("you", "your")
- No em dashes anywhere
- No filler sentences - every sentence adds value
- Max 3 bolded terms per article, only on first definition
- Include specific numbers, percentages, real examples
- Vary sentence length - mix short punchy sentences with longer ones
- Pick one of these formats: numbered tips list, deep guide with 5 H2 sections, question-driven sections, or story-led intro
- Naturally mention 1-2 of these affiliate tools where relevant: Robinhood, Betterment, SoFi, YNAB, Acorns, Fundrise
- End with a FAQ section (5-6 questions)

TRANSCRIPT:
{transcript}

Write the complete article now. Output only the article in markdown, no preamble.
"""

    from google.genai import types
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            max_output_tokens=4000,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    record_request()
    content = response.text

    lines = content.strip().split("\n")
    title = lines[0].replace("# ", "").strip() if lines else topic_hint
    meta = ""
    if len(lines) > 1 and lines[1].startswith("[") and lines[1].endswith("]"):
        meta = lines[1][1:-1]

    word_count = len(content.split())
    return {
        "title":      title,
        "meta":       meta,
        "content":    content,
        "word_count": word_count,
        "keyword":    topic_hint,
        "niche":      "finance",
    }


def save_article(article: dict) -> Path:
    output_dir = TMP_DIR / "articles" / article["niche"]
    output_dir.mkdir(parents=True, exist_ok=True)

    slug = re.sub(r"[^a-z0-9]+", "-", article["keyword"].lower()).strip("-")
    filename = output_dir / f"{slug}.md"

    header = f"""---
keyword: {article['keyword']}
title: {article['title']}
meta: {article['meta']}
niche: {article['niche']}
word_count: {article['word_count']}
generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}
source: youtube
status: draft
---

"""
    filename.write_text(header + article["content"], encoding="utf-8")
    return filename


def process_video(video_id: str, topic_hint: str, client) -> dict:
    print(f"  Fetching transcript for: {video_id} ({topic_hint})")
    try:
        transcript = get_transcript(video_id)
        word_count_t = len(transcript.split())
        print(f"  Transcript: {word_count_t} words")
    except RuntimeError as e:
        return {"status": "error", "reason": str(e)}

    print(f"  Generating article...")
    start = time.time()
    try:
        article = transcript_to_article(transcript, topic_hint, client)
        path = save_article(article)
        elapsed = time.time() - start
        print(f"  Done: {article['word_count']} words in {elapsed:.1f}s -> {path.name}")
        return {"status": "ok", "path": str(path), "words": article["word_count"]}
    except Exception as e:
        return {"status": "error", "reason": str(e)}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Mine YouTube videos for SEO articles")
    parser.add_argument("--url",          help="Single YouTube video URL")
    parser.add_argument("--file",         help="Text file with one YouTube URL per line")
    parser.add_argument("--top-creators", action="store_true", help="Use built-in top creator video list")
    parser.add_argument("--limit",        type=int, default=5, help="Max videos to process")
    parser.add_argument("--topic",        help="Topic hint for single URL mode")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not set in .env")
    client = genai.Client(api_key=api_key)

    usage = get_usage()
    print(f"Gemini usage today: {usage['requests']}/{DAILY_LIMIT}")

    videos = []

    if args.url:
        vid_id = extract_video_id(args.url)
        topic  = args.topic or "personal finance tips"
        videos = [(vid_id, "YouTube", topic)]

    elif args.file:
        lines = Path(args.file).read_text().splitlines()
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|", 1)
            url   = parts[0].strip()
            topic = parts[1].strip() if len(parts) > 1 else "personal finance tips"
            try:
                vid_id = extract_video_id(url)
                videos.append((vid_id, "YouTube", topic))
            except ValueError as e:
                print(f"  Skipping invalid URL: {e}")

    elif args.top_creators:
        videos = TOP_CREATOR_VIDEOS

    else:
        parser.print_help()
        return

    videos = videos[:args.limit]
    print(f"Processing {len(videos)} videos\n" + "-" * 50)

    results = []
    for i, (vid_id, channel, topic) in enumerate(videos):
        print(f"\n[{i+1}/{len(videos)}] {channel}")
        result = process_video(vid_id, topic, client)
        results.append(result)
        if i < len(videos) - 1:
            time.sleep(3)

    ok = sum(1 for r in results if r["status"] == "ok")
    print(f"\nDone: {ok}/{len(videos)} articles generated")
    print(f"Gemini usage: {get_usage()['requests']}/{DAILY_LIMIT} today")


if __name__ == "__main__":
    main()
