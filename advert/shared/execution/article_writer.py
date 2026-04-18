"""
article_writer.py

Generates full SEO articles using Claude API.
Takes a keyword + niche and outputs a complete, publish-ready article.

Usage:
    python shared/execution/article_writer.py --keyword "best credit cards for beginners" --niche finance
    python shared/execution/article_writer.py --batch .tmp/keywords_finance_20260403.csv --niche finance --limit 10

Output: Markdown files saved to .tmp/articles/<niche>/
"""

import argparse
import csv
import os
import re
import time
from datetime import datetime
from pathlib import Path

from google import genai

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


def check_limit(needed: int = 1):
    usage = get_usage()
    remaining = DAILY_LIMIT - usage["requests"]
    if remaining < needed:
        raise RuntimeError(
            f"Daily Gemini limit reached ({usage['requests']}/{DAILY_LIMIT}). "
            f"Resets tomorrow. Use --status to check usage."
        )
    return remaining


# ---------------------------------------------------------------------------
# Affiliate programs per niche (injected naturally into articles)
# ---------------------------------------------------------------------------

AFFILIATE_CONFIG = ADVERT_ROOT / "finance" / "directives" / "affiliate_links.json"


def get_affiliate_mentions(niche: str) -> list:
    """Return affiliate descriptions with real URLs if available, else generic."""
    import json
    if niche == "finance" and AFFILIATE_CONFIG.exists():
        data = json.loads(AFFILIATE_CONFIG.read_text())
        mentions = []
        for p in data["programs"]:
            url = p["url"]
            if url.startswith("YOUR_"):
                mentions.append(f"{p['name']} ({p['commission']} commission)")
            else:
                mentions.append(f"{p['name']} - link: {url} ({p['commission']} commission)")
        return mentions
    return AFFILIATES_FALLBACK.get(niche, [])


AFFILIATES_FALLBACK = {
    "finance": [
        "Robinhood (commission-free investing)",
        "Betterment (automated investing)",
        "SoFi (loans, investing, banking)",
        "YNAB - You Need A Budget (budgeting app)",
        "Acorns (micro-investing)",
        "Fundrise (real estate investing)",
        "Coinbase (buy crypto - $10 per user who trades $100+)",
    ],
    "health": [
        "Noom (weight loss program)",
        "Calm (meditation app)",
        "Athletic Greens AG1 (greens supplement)",
        "Thorne (supplements)",
        "MyFitnessPal (calorie tracking)",
        "BetterHelp (online therapy)",
        "Whoop (fitness tracker)",
    ],
}


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

import random

LENGTH_PRESETS = [
    {"label": "short",  "words": 500,  "minutes": 2,  "tokens": 1200},
    {"label": "short",  "words": 500,  "minutes": 2,  "tokens": 1200},
    {"label": "medium", "words": 900,  "minutes": 4,  "tokens": 2000},
    {"label": "medium", "words": 900,  "minutes": 4,  "tokens": 2000},
    {"label": "medium", "words": 900,  "minutes": 4,  "tokens": 2000},
    {"label": "long",   "words": 1600, "minutes": 8,  "tokens": 3500},
    {"label": "long",   "words": 1600, "minutes": 8,  "tokens": 3500},
]


def build_prompt(keyword: str, niche: str, preset: dict = None) -> str:
    if preset is None:
        preset = random.choice(LENGTH_PRESETS)
    affiliate_list = "\n".join(f"- {a}" for a in get_affiliate_mentions(niche))

    niche_context = {
        "finance": "personal finance for young adults, writing for The Finance Blueprint (financeblueprint.com). Tone: like a smart friend explaining money, not a bank. Practical, no jargon without explanation, slightly conversational. Author name is Jordan Hale.",
        "health": "health and wellness for everyday people. Tone: supportive, science-backed but accessible, not preachy. Practical advice that people can actually follow.",
    }.get(niche, "general information. Tone: clear, helpful, practical.")

    return f"""You are an expert SEO content writer specializing in {niche_context}

Write a complete, publish-ready SEO article targeting the keyword: "{keyword}"

ARTICLE REQUIREMENTS:
- Length: {preset['words']} words. This is a strict target - do not go more than 100 words over or under.
- Target read time: {preset['minutes']} minutes. Every word must earn its place.
- Naturally include the target keyword in: title, first paragraph, at least 2 subheadings, conclusion
- Use H2 (##) subheadings only - no H3s
- Write in second person ("you", "your") to feel direct and personal
- No fluff, no filler sentences. Every sentence must add value.
- No em dashes anywhere in the article
- Do NOT bold random words. Only bold a word if it is a critical term being defined for the first time. Maximum 3 bolded terms per article.
- Vary your sentence length. Mix short punchy sentences with longer ones.
- Write like a real person, not a content mill. Include specific numbers, real examples, and occasional opinions.

STRUCTURE:
Use one of these formats randomly - do NOT always use the same structure:

Format A (List-driven):
- Title, meta, intro, numbered list of 5-7 tips (each with 2-3 sentences of explanation), one comparison table, conclusion with next step

Format B (Guide-style):
- Title, meta, intro with a personal anecdote or scenario, TL;DR box (3 bullet points), 4 H2 sections, real examples with numbers, conclusion with next step

Format C (Question-driven):
- Title, meta, start with the question the reader is asking, answer it in 2 sentences, then 4-5 H2 sections each as a question, end with a 5-point summary checklist

Format D (Story-led):
- Title, meta, 2-sentence story opener, transition to practical advice, 4 H2 sections, 1 blockquote with a key insight, conclusion with next step

Pick whichever format fits the keyword best. Vary sentence length. Do NOT bold random words. Only bold genuinely critical terms on first use, max 3 times.

WORD COUNT REMINDER: Stop writing at {preset['words']} words. Count as you go. Wrap up immediately when you hit the target.

FEATURED SNIPPET OPTIMIZATION:
- After your very first H2 heading, write a direct 40-60 word answer to the main question. Label it nothing - just write it as a clean paragraph. This is what Google pulls for the answer box.
- Use numbered lists for any "steps" or "ways" content
- Use a comparison table wherever you compare 2+ options

AFFILIATE MENTIONS:
Naturally recommend 1-2 of these tools where genuinely relevant to the topic. Do not force it. Only mention if it actually fits the context:
{affiliate_list}

FORMAT:
- Output plain markdown only
- No preamble, no "here is the article" - start directly with the title
- Use bullet points and numbered lists where helpful
- Bold key terms on first use
"""


# ---------------------------------------------------------------------------
# Article generation
# ---------------------------------------------------------------------------

def generate_article(keyword: str, niche: str, client) -> dict:
    preset = random.choice(LENGTH_PRESETS)
    prompt = build_prompt(keyword, niche, preset)

    check_limit()
    print(f"  Generating: '{keyword}'")
    start = time.time()

    from google.genai import types
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            max_output_tokens=preset["tokens"],
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    record_request()
    content = response.text
    elapsed = time.time() - start

    # Extract title from first line
    lines = content.strip().split("\n")
    title = lines[0].replace("# ", "").strip() if lines else keyword

    # Extract meta description if present (in brackets on line 2)
    meta = ""
    if len(lines) > 1 and lines[1].startswith("[") and lines[1].endswith("]"):
        meta = lines[1][1:-1]

    word_count = len(content.split())

    print(f"  Done: {word_count} words in {elapsed:.1f}s")

    return {
        "keyword": keyword,
        "title": title,
        "meta": meta,
        "content": content,
        "word_count": word_count,
        "niche": niche,
    }


def save_article(article: dict, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)

    # Filename from keyword
    slug = re.sub(r"[^a-z0-9]+", "-", article["keyword"].lower()).strip("-")
    filename = output_dir / f"{slug}.md"

    # Add metadata header
    header = f"""---
keyword: {article['keyword']}
title: {article['title']}
meta: {article['meta']}
niche: {article['niche']}
word_count: {article['word_count']}
generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}
status: draft
---

"""
    filename.write_text(header + article["content"], encoding="utf-8")
    return filename


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def get_model():
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not set in .env")
    return genai.Client(api_key=api_key)


def run_single(keyword: str, niche: str):
    model = get_model()
    output_dir = TMP_DIR / "articles" / niche

    article = generate_article(keyword, niche, model)
    path = save_article(article, output_dir)
    print(f"\nSaved to: {path}")
    print(f"Title: {article['title']}")
    print(f"Words: {article['word_count']}")
    return path


def run_batch(csv_path: str, niche: str, limit: int):
    model = get_model()
    output_dir = TMP_DIR / "articles" / niche

    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        keywords = [row["keyword"] for row in reader]

    remaining = check_limit(1)
    limit = min(limit, remaining)
    keywords = keywords[:limit]
    print(f"\nGenerating {len(keywords)} articles for niche: {niche}")
    print(f"Gemini usage today: {get_usage()['requests']}/{DAILY_LIMIT} requests")
    print("-" * 50)

    results = []
    for i, kw in enumerate(keywords):
        print(f"\n[{i+1}/{len(keywords)}]", end=" ")
        try:
            article = generate_article(kw, niche, model)
            path = save_article(article, output_dir)
            results.append({"keyword": kw, "path": str(path), "words": article["word_count"], "status": "ok"})
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({"keyword": kw, "path": "", "words": 0, "status": f"error: {e}"})

        # Rate limit: pause between articles
        if i < len(keywords) - 1:
            time.sleep(2)

    # Summary
    ok = sum(1 for r in results if r["status"] == "ok")
    print(f"\nDone: {ok}/{len(keywords)} articles generated")
    print(f"Saved to: {output_dir}")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyword", help="Single keyword to write article for")
    parser.add_argument("--niche",   default="finance", help="finance or health")
    parser.add_argument("--batch",   help="Path to keywords CSV for batch generation")
    parser.add_argument("--limit",   type=int, default=5, help="Max articles in batch mode")
    parser.add_argument("--status",  action="store_true", help="Show today's Gemini usage")
    args = parser.parse_args()

    if args.status:
        usage = get_usage()
        print(f"Gemini usage today: {usage['requests']}/{DAILY_LIMIT} requests used")
        print(f"Remaining: {DAILY_LIMIT - usage['requests']}")
    elif args.batch:
        run_batch(args.batch, args.niche, args.limit)
    elif args.keyword:
        run_single(args.keyword, args.niche)
    else:
        print("Provide --keyword, --batch, or --status")
