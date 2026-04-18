"""
daily_pipeline.py

Runs every day automatically:
  - Generates 15 new articles from unused keywords
  - Deploys to the site
  - Logs results

Usage:
    python shared/execution/daily_pipeline.py           # run once
    python shared/execution/daily_pipeline.py --loop    # run daily forever

Schedule (Windows Task Scheduler):
    Action: python "C:/Program Files/Projects/advert/shared/execution/daily_pipeline.py"
    Trigger: Daily at 6:00 AM
"""

import json
import os
import sys
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

TMP_DIR      = PROJECT_ROOT / ".tmp"
LOG_FILE     = TMP_DIR / "daily_pipeline.log"
USED_FILE    = TMP_DIR / "used_keywords_finance.txt"
KEYWORDS_CSV = TMP_DIR / "keywords_finance_20260404_1325.csv"

ARTICLES_PER_DAY = 3
DAILY_LIMIT      = 1500


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def get_gemini_usage() -> int:
    usage_file = TMP_DIR / "gemini_usage.json"
    if usage_file.exists():
        data = json.loads(usage_file.read_text())
        if data.get("date") == datetime.now().strftime("%Y-%m-%d"):
            return data.get("requests", 0)
    return 0


def get_used_keywords() -> set:
    if USED_FILE.exists():
        return set(USED_FILE.read_text(encoding="utf-8").splitlines())
    return set()


def mark_used(keywords: list):
    used = get_used_keywords()
    used.update(keywords)
    USED_FILE.write_text("\n".join(sorted(used)), encoding="utf-8")


def get_next_keywords(n: int) -> list:
    import csv
    used = get_used_keywords()
    keywords = []
    with open(KEYWORDS_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            kw = row["keyword"].strip()
            if kw and kw not in used:
                keywords.append(kw)
            if len(keywords) >= n:
                break
    return keywords


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_pipeline():
    log("=" * 60)
    log(f"Daily pipeline starting - target: {ARTICLES_PER_DAY} articles")

    # Check Gemini headroom
    used_today = get_gemini_usage()
    remaining  = DAILY_LIMIT - used_today
    if remaining < 1:
        log(f"Gemini daily limit reached ({used_today}/{DAILY_LIMIT}). Skipping.")
        return
    count = min(ARTICLES_PER_DAY, remaining)
    log(f"Gemini usage: {used_today}/{DAILY_LIMIT} - generating {count} articles")

    # Get unused keywords
    keywords = get_next_keywords(count)
    if not keywords:
        log("No unused keywords left. Run keyword_research.py to get more.")
        return
    log(f"Keywords selected: {len(keywords)}")

    # Generate articles
    from article_writer import get_model, generate_article, save_article

    client     = get_model()
    output_dir = TMP_DIR / "articles" / "finance"
    succeeded  = []
    failed     = []

    for i, kw in enumerate(keywords):
        log(f"  [{i+1}/{len(keywords)}] Generating: '{kw}'")
        try:
            article = generate_article(kw, "finance", client)
            save_article(article, output_dir)
            succeeded.append(kw)
            log(f"  Done: {article['word_count']} words")
        except Exception as e:
            log(f"  ERROR: {e}")
            failed.append(kw)
        if i < len(keywords) - 1:
            time.sleep(3)

    mark_used(succeeded)
    log(f"Articles generated: {len(succeeded)}/{len(keywords)}")
    if failed:
        log(f"Failed: {failed}")

    # Deploy
    log("Deploying site...")
    import subprocess
    result = subprocess.run(
        [sys.executable, "shared/execution/deploy.py", f"Daily batch: {len(succeeded)} new articles"],
        cwd=ADVERT_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        log("Deploy successful.")
    else:
        log(f"Deploy failed: {result.stderr.strip()}")

    log(f"Pipeline complete. Gemini usage: {get_gemini_usage()}/{DAILY_LIMIT}")


def seconds_until_6am() -> float:
    now  = datetime.now()
    next_run = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if now >= next_run:
        from datetime import timedelta
        next_run += timedelta(days=1)
    return (next_run - now).total_seconds()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--loop" in sys.argv:
        log("Daily pipeline loop started. Runs every day at 6:00 AM.")
        while True:
            run_pipeline()
            wait = seconds_until_6am()
            log(f"Next run in {wait/3600:.1f} hours (6:00 AM).")
            time.sleep(wait)
    else:
        run_pipeline()
