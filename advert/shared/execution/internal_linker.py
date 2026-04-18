"""
internal_linker.py

Scans all articles and injects internal links wherever one article's
keyword phrase is mentioned in another article's body.

Rules:
  - Only links the FIRST occurrence per target article per source article
  - Max 5 internal links added per article (avoid over-optimisation)
  - Skips mentions already inside a markdown link
  - Never links an article to itself

Usage:
    python shared/execution/internal_linker.py          # dry run (preview)
    python shared/execution/internal_linker.py --apply  # write changes
"""

import argparse
import re
from pathlib import Path

ADVERT_ROOT  = Path(__file__).parent.parent.parent
PROJECT_ROOT = ADVERT_ROOT.parent
ARTICLES_DIR = PROJECT_ROOT / ".tmp" / "articles" / "finance"

MAX_LINKS_PER_ARTICLE = 5

STOPWORDS = {
    "a", "an", "the", "how", "to", "for", "in", "on", "at", "with",
    "best", "top", "free", "what", "is", "are", "vs", "and", "or",
    "of", "your", "my", "our", "their", "its", "do", "i", "you",
    "should", "can", "will", "get", "make", "take", "much", "more",
    "why", "when", "where", "which", "who", "about", "up", "out",
    "from", "as", "by", "into", "through", "than", "so", "that",
    "this", "these", "those", "no", "not", "be", "been", "has",
    "have", "had", "was", "were", "am", "if",
}

# Phrases that are too generic or date-like to use as anchors
JUNK_PATTERNS = [
    r"^\d{4}$",            # bare year: 2025, 2026
    r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{4}$",  # month year
    r"^(january|february|march|april|june|july|august|september|october|november|december)\s+\d{4}$",
    r"^\w+ \d{4}$",        # anything + 4-digit year e.g. "july 2025"
]

def is_junk_phrase(phrase: str) -> bool:
    for pat in JUNK_PATTERNS:
        if re.match(pat, phrase, re.IGNORECASE):
            return True
    return False


def extract_anchor_phrases(keyword: str) -> list[str]:
    """Return a ranked list of anchor phrases for a keyword, longest first."""
    phrases = [keyword]  # always try exact match first

    words = keyword.split()
    # Strip leading stopwords to get the core phrase
    stripped = words[:]
    while stripped and stripped[0] in STOPWORDS:
        stripped = stripped[1:]

    core = " ".join(stripped)
    if core and core != keyword:
        phrases.append(core)

    # Also try all 2-4 word windows from the stripped words
    for size in (4, 3, 2):
        for i in range(len(stripped) - size + 1):
            chunk = " ".join(stripped[i:i + size])
            # Skip if starts or ends with a stopword
            if stripped[i] not in STOPWORDS and stripped[i + size - 1] not in STOPWORDS:
                if chunk not in phrases:
                    phrases.append(chunk)

    return phrases


def parse_frontmatter(text: str) -> tuple[str, str]:
    """Return (frontmatter_block, body) split on closing ---."""
    if not text.startswith("---"):
        return "", text
    close = text.index("---", 3)
    return text[:close + 3], text[close + 3:].lstrip("\n")


def get_articles() -> list[dict]:
    articles = []
    for path in sorted(ARTICLES_DIR.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        fm_block, body = parse_frontmatter(raw)

        # Pull keyword from frontmatter
        keyword = ""
        for line in fm_block.splitlines():
            if line.startswith("keyword:"):
                keyword = line.split(":", 1)[1].strip().strip('"').lower()
                break

        if not keyword:
            continue

        articles.append({
            "path":    path,
            "slug":    path.stem,
            "keyword": keyword,
            "url":     f"/{path.stem}/",
            "fm":      fm_block,
            "body":    body,
        })

    return articles


def inject_links(body: str, source_slug: str, targets: list[dict]) -> tuple[str, list[str]]:
    injected = []
    links_added = 0
    used_phrases: set[str] = set()  # each anchor phrase used at most once per article

    for target in targets:
        if links_added >= MAX_LINKS_PER_ARTICLE:
            break
        if target["slug"] == source_slug:
            continue

        url = target["url"]
        matched_phrase = None

        for phrase in extract_anchor_phrases(target["keyword"]):
            words = phrase.split()
            if len(words) < 2:
                continue
            if is_junk_phrase(phrase):
                continue
            if phrase.lower() in used_phrases:
                continue  # already used this anchor text for another target

            pattern = rf'(?<!\[)(?<!\()(\b{re.escape(phrase)}\b)(?!\]|\))'

            count = 0
            def replace(m):
                nonlocal count
                if count == 0:
                    count += 1
                    return f"[{m.group(1)}]({url})"
                return m.group(1)

            new_body = re.sub(pattern, replace, body, flags=re.IGNORECASE)
            if new_body != body:
                matched_phrase = phrase
                body = new_body
                used_phrases.add(phrase.lower())
                break

        if matched_phrase:
            injected.append(matched_phrase)
            links_added += 1

    return body, injected


def run(apply: bool = False):
    articles = get_articles()
    print(f"Loaded {len(articles)} articles")
    print(f"Mode: {'APPLY' if apply else 'DRY RUN (preview only)'}")
    print("=" * 60)

    total_injected = 0

    for article in articles:
        new_body, injected = inject_links(article["body"], article["slug"], articles)

        if injected:
            total_injected += len(injected)
            print(f"  {article['slug'][:52]}: +{len(injected)} links")
            for kw in injected:
                print(f"    -> {kw}")
            if apply:
                new_text = article["fm"] + "\n" + new_body
                article["path"].write_text(new_text, encoding="utf-8")

    print(f"\nTotal internal links injected: {total_injected}")
    if not apply:
        print("Run with --apply to write changes, then deploy.")
    else:
        print("Done. Run deploy.py to publish.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Write changes (default is dry run)")
    args = parser.parse_args()
    run(apply=args.apply)
