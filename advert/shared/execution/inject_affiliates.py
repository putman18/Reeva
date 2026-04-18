"""
inject_affiliates.py

Scans all existing articles and injects real affiliate links wherever
a partner brand is mentioned by name. Only injects once per article per brand.

Run this after adding a new affiliate URL to affiliate_links.json.

Usage:
    python shared/execution/inject_affiliates.py          # dry run (preview only)
    python shared/execution/inject_affiliates.py --apply  # actually inject links
"""

import argparse
import json
import re
from pathlib import Path

ADVERT_ROOT  = Path(__file__).parent.parent.parent
PROJECT_ROOT = ADVERT_ROOT.parent
TMP_DIR      = PROJECT_ROOT / ".tmp"
ARTICLES_DIR = TMP_DIR / "articles" / "finance"
AFFILIATE_CONFIG = ADVERT_ROOT / "finance" / "directives" / "affiliate_links.json"


def get_active_affiliates() -> list:
    data = json.loads(AFFILIATE_CONFIG.read_text())
    return [p for p in data["programs"] if not p["url"].startswith("YOUR_")]


def inject_links(text: str, affiliates: list) -> tuple[str, list]:
    injected = []
    for p in affiliates:
        name = p["name"]
        url  = p["url"]
        # Match brand name as a whole word, not already inside a markdown link
        pattern = rf'(?<!\[)(?<!\()(\b{re.escape(name)}\b)(?!\]|\))'
        # Only inject the FIRST occurrence per article
        count = 0
        def replace(m):
            nonlocal count
            if count == 0:
                count += 1
                return f"[{m.group(1)}]({url})"
            return m.group(1)
        new_text = re.sub(pattern, replace, text, flags=re.IGNORECASE)
        if new_text != text:
            injected.append(name)
            text = new_text
    return text, injected


def run(apply: bool = False):
    affiliates = get_active_affiliates()
    if not affiliates:
        print("No active affiliate URLs found in affiliate_links.json.")
        print("Add your affiliate URLs first, then run this script.")
        return

    print(f"Active affiliates: {[a['name'] for a in affiliates]}")
    print(f"Mode: {'APPLY' if apply else 'DRY RUN (preview only)'}")
    print("=" * 60)

    md_files    = list(ARTICLES_DIR.glob("*.md"))
    total_injected = 0

    for path in sorted(md_files):
        text        = path.read_text(encoding="utf-8")
        new_text, injected = inject_links(text, affiliates)

        if injected:
            total_injected += len(injected)
            print(f"  {path.stem[:50]}: injected {injected}")
            if apply:
                path.write_text(new_text, encoding="utf-8")

    print(f"\nTotal injections: {total_injected} across {len(md_files)} articles")
    if not apply:
        print("\nRun with --apply to actually inject the links.")
    else:
        print("\nDone. Run deploy.py to publish changes.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Apply changes (default is dry run)")
    args = parser.parse_args()
    run(apply=args.apply)
