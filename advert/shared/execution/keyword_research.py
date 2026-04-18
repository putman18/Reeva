"""
keyword_research.py

Finds low-competition keyword opportunities using free sources:
- Google Autocomplete (what people actually type)
- Google "People Also Ask" suggestions
- Alphabet soup method (keyword + a, b, c... to get all variations)

Usage:
    python shared/execution/keyword_research.py --niche finance
    python shared/execution/keyword_research.py --niche health
    python shared/execution/keyword_research.py --seed "best credit cards" --niche finance

Output: CSV saved to .tmp/keywords_<niche>_<date>.csv
"""

import argparse
import csv
import json
import os
import time
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path

ADVERT_ROOT  = Path(__file__).parent.parent.parent
PROJECT_ROOT = ADVERT_ROOT.parent
TMP_DIR      = PROJECT_ROOT / ".tmp"
TMP_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Seed keywords per niche
# ---------------------------------------------------------------------------

SEEDS = {
    "finance": [
        "best credit cards",
        "how to invest money",
        "how to save money",
        "best budgeting apps",
        "how to pay off debt",
        "best brokerage accounts",
        "how to build credit",
        "passive income ideas",
        "side hustles",
        "how to start investing",
        "best savings accounts",
        "how to make money",
        "personal finance tips",
        "how to budget",
        "credit score",
    ],
    "health": [
        "how to lose weight",
        "best supplements",
        "how to sleep better",
        "mental health tips",
        "how to build muscle",
        "best protein powder",
        "healthy meal prep",
        "how to reduce stress",
        "best vitamins",
        "gut health",
    ],
}


# ---------------------------------------------------------------------------
# Google Autocomplete
# ---------------------------------------------------------------------------

def get_autocomplete(query: str) -> list[str]:
    """Fetch Google autocomplete suggestions for a query."""
    encoded = urllib.parse.quote(query)
    url = f"https://suggestqueries.google.com/complete/search?client=firefox&q={encoded}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
            return data[1] if len(data) > 1 else []
    except Exception as e:
        print(f"  Autocomplete error for '{query}': {e}")
        return []


def alphabet_soup(seed: str) -> list[str]:
    """
    Expand a seed keyword using alphabet soup method.
    Queries seed + each letter a-z to get all autocomplete variations.
    """
    results = []
    results.extend(get_autocomplete(seed))

    for char in "abcdefghijklmnopqrstuvwxyz":
        suggestions = get_autocomplete(f"{seed} {char}")
        results.extend(suggestions)
        time.sleep(0.15)  # polite rate limiting

    return list(set(results))


# ---------------------------------------------------------------------------
# Keyword scoring (rough quality filter)
# ---------------------------------------------------------------------------

COMMERCIAL_WORDS = [
    "best", "top", "review", "vs", "versus", "compare", "cheapest",
    "affordable", "how to", "what is", "tips", "guide", "free", "easy",
    "for beginners", "step by step", "2025", "2026",
]

LOW_VALUE_WORDS = [
    "reddit", "wiki", "wikipedia", "youtube", "login", "sign in",
    "phone number", "address", "near me", "hours",
]

def score_keyword(kw: str) -> dict:
    """
    Score a keyword for content potential.
    Returns dict with keyword, score, intent type.
    """
    kw_lower = kw.lower()

    # Skip low value
    if any(w in kw_lower for w in LOW_VALUE_WORDS):
        return None

    # Skip very short keywords (too broad, too competitive)
    words = kw.split()
    if len(words) < 3:
        return None

    # Score based on signals
    score = 0

    # Commercial intent words
    for w in COMMERCIAL_WORDS:
        if w in kw_lower:
            score += 2

    # Long tail (4+ words = lower competition)
    if len(words) >= 4:
        score += 2
    if len(words) >= 5:
        score += 1

    # Question format (good for featured snippets)
    if kw_lower.startswith(("how", "what", "why", "when", "which", "is ", "can ", "does ")):
        score += 2
        intent = "informational"
    elif any(w in kw_lower for w in ["best", "top", "review", "vs", "compare"]):
        intent = "commercial"
        score += 3
    else:
        intent = "informational"

    return {
        "keyword": kw,
        "word_count": len(words),
        "score": score,
        "intent": intent,
    }


# ---------------------------------------------------------------------------
# Suggested article title generator
# ---------------------------------------------------------------------------

def suggest_title(kw: str, intent: str) -> str:
    """Generate a clickable article title from a keyword."""
    kw_title = kw.title()
    year = "2026"

    if intent == "commercial":
        return f"Best {kw_title.replace('Best ', '')}: Top Picks for {year}"
    elif kw.lower().startswith("how to"):
        return f"{kw_title}: A Step-by-Step Guide"
    elif kw.lower().startswith("what is"):
        return f"{kw_title} Explained Simply"
    else:
        return f"{kw_title}: Everything You Need to Know"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(niche: str, extra_seed: str = None):
    seeds = SEEDS.get(niche, [])
    if extra_seed:
        seeds = [extra_seed] + seeds

    if not seeds:
        print(f"Unknown niche '{niche}'. Use: {list(SEEDS.keys())}")
        return

    print(f"\nKeyword research for niche: {niche}")
    print(f"Seeds: {len(seeds)} starting keywords")
    print("-" * 50)

    all_keywords = []

    for i, seed in enumerate(seeds):
        print(f"[{i+1}/{len(seeds)}] Expanding: '{seed}'")
        suggestions = alphabet_soup(seed)
        print(f"  Found {len(suggestions)} suggestions")
        all_keywords.extend(suggestions)
        time.sleep(0.5)

    # Deduplicate
    all_keywords = list(set(kw.strip().lower() for kw in all_keywords if kw.strip()))
    print(f"\nTotal unique keywords: {len(all_keywords)}")

    # Score and filter
    scored = []
    for kw in all_keywords:
        result = score_keyword(kw)
        if result and result["score"] >= 3:
            result["suggested_title"] = suggest_title(kw, result["intent"])
            scored.append(result)

    # Sort by score descending
    scored.sort(key=lambda x: x["score"], reverse=True)
    print(f"Qualified keywords (score >= 3): {len(scored)}")

    # Save to CSV
    date_str = datetime.now().strftime("%Y%m%d_%H%M")
    output_path = TMP_DIR / f"keywords_{niche}_{date_str}.csv"

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["keyword", "word_count", "score", "intent", "suggested_title"])
        writer.writeheader()
        writer.writerows(scored)

    print(f"\nSaved {len(scored)} keywords to: {output_path}")
    print("\nTop 20 keywords:")
    print(f"{'Score':<6} {'Intent':<14} {'Keyword'}")
    print("-" * 60)
    for row in scored[:20]:
        print(f"{row['score']:<6} {row['intent']:<14} {row['keyword']}")

    return output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--niche", default="finance", help="finance or health")
    parser.add_argument("--seed", default=None, help="Extra seed keyword to add")
    args = parser.parse_args()

    run(niche=args.niche, extra_seed=args.seed)
