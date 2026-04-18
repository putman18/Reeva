"""
daily_publisher.py

Runs daily: generates N articles and publishes them to Ghost.
Designed to run as a scheduled task or loop.

Usage:
    python shared/execution/daily_publisher.py --niche finance --count 5
    python shared/execution/daily_publisher.py --niche finance --count 5 --loop
"""

import argparse
import csv
import os
import time
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

import sys
sys.path.insert(0, str(Path(__file__).parent))
from article_writer import generate_article, save_article, get_model
from publisher import publish_article, parse_article

TMP_DIR = PROJECT_ROOT / ".tmp"


# ---------------------------------------------------------------------------
# Keyword queue management
# ---------------------------------------------------------------------------

def load_keyword_queue(niche: str) -> list[dict]:
    """Load unused keywords from the most recent keyword CSV."""
    csvs = sorted(TMP_DIR.glob(f"keywords_{niche}_*.csv"), reverse=True)
    if not csvs:
        print(f"No keyword CSV found for niche '{niche}'. Run keyword_research.py first.")
        return []

    latest = csvs[0]
    used_file = TMP_DIR / f"used_keywords_{niche}.txt"
    used = set(used_file.read_text(encoding="utf-8").splitlines()) if used_file.exists() else set()

    queue = []
    with open(latest, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            kw = row["keyword"].strip()
            if kw and kw not in used:
                queue.append(row)

    print(f"Keyword queue: {len(queue)} unused keywords available")
    return queue


def mark_used(keyword: str, niche: str):
    used_file = TMP_DIR / f"used_keywords_{niche}.txt"
    with open(used_file, "a", encoding="utf-8") as f:
        f.write(keyword + "\n")


# ---------------------------------------------------------------------------
# Daily run
# ---------------------------------------------------------------------------

def run_daily(niche: str, count: int):
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Daily publish - {niche} - {count} articles")
    print("-" * 60)

    queue = load_keyword_queue(niche)
    if not queue:
        print("No keywords left in queue. Run keyword_research.py to get more.")
        return

    keywords = queue[:count]
    model = get_model()
    output_dir = TMP_DIR / "articles" / niche

    published = 0
    for i, row in enumerate(keywords):
        kw = row["keyword"]
        print(f"\n[{i+1}/{len(keywords)}] {kw}")

        try:
            # Generate
            article = generate_article(kw, niche, model)
            path = save_article(article, output_dir)

            # Publish
            parsed = parse_article(path)
            url = publish_article(parsed)
            print(f"  Live: {url}")

            # Mark keyword as used
            mark_used(kw, niche)

            # Update file status
            text = path.read_text(encoding="utf-8")
            path.write_text(text.replace("status: draft", "status: published"), encoding="utf-8")

            published += 1

        except Exception as e:
            print(f"  ERROR: {e}")

        # Pause between articles
        if i < len(keywords) - 1:
            time.sleep(3)

    print(f"\nDone. Published {published}/{len(keywords)} articles.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--niche",  default="finance")
    parser.add_argument("--count",  type=int, default=5, help="Articles per day")
    parser.add_argument("--loop",   action="store_true", help="Run every 24 hours")
    args = parser.parse_args()

    if args.loop:
        print(f"Starting daily loop: {args.count} articles/day for niche '{args.niche}'")
        while True:
            run_daily(args.niche, args.count)
            print(f"\nSleeping 24 hours until next run...")
            time.sleep(86400)
    else:
        run_daily(args.niche, args.count)
