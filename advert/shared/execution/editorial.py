"""
editorial.py

Reviews and improves existing articles for quality, accuracy, and SEO.
Acts like an editorial team - checks each article against quality standards
and rewrites sections that fail.

Checks:
  - No em dashes
  - Has a direct answer paragraph after first H2 (featured snippet)
  - Meta description is present and under 155 chars
  - Title is compelling and includes keyword
  - Word count is in acceptable range (400-2000)
  - No duplicate content (same keyword written twice)

Usage:
    python shared/execution/editorial.py             # review all articles
    python shared/execution/editorial.py --fix       # review + auto-fix with Gemini
    python shared/execution/editorial.py --report    # report only, no changes
"""

import argparse
import os
import re
import json
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
REPORT_FILE  = TMP_DIR / "editorial_report.json"


# ---------------------------------------------------------------------------
# Quality checks
# ---------------------------------------------------------------------------

def check_article(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    issues = []

    # Parse frontmatter
    meta = {}
    body = text
    if text.startswith("---"):
        end = text.index("---", 3)
        for line in text[3:end].strip().splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                meta[k.strip()] = v.strip()
        body = text[end+3:].strip()

    word_count = len(body.split())
    keyword    = meta.get("keyword", path.stem)

    # Check: em dashes
    if "\u2014" in body or " -- " in body:
        issues.append("contains_em_dash")

    # Check: meta description
    meta_desc = meta.get("meta", "")
    if not meta_desc or meta_desc.startswith("YOUR_"):
        issues.append("missing_meta_description")
    elif len(meta_desc) > 155:
        issues.append("meta_description_too_long")

    # Check: word count
    if word_count < 350:
        issues.append(f"too_short_{word_count}_words")
    elif word_count > 2500:
        issues.append(f"too_long_{word_count}_words")

    # Check: has H2 headings
    h2_count = len(re.findall(r"^## ", body, re.MULTILINE))
    if h2_count < 2:
        issues.append("insufficient_headings")

    # Check: keyword in title
    lines = body.splitlines()
    title = ""
    for line in lines:
        if line.startswith("# "):
            title = line[2:].lower()
            break
    if keyword.lower() not in title and not any(w in title for w in keyword.lower().split()):
        issues.append("keyword_not_in_title")

    # Check: direct answer after first H2 (featured snippet readiness)
    h2_match = re.search(r"^## .+\n+(.+)", body, re.MULTILINE)
    if h2_match:
        first_para_after_h2 = h2_match.group(1).strip()
        if len(first_para_after_h2.split()) < 20:
            issues.append("no_featured_snippet_paragraph")

    return {
        "file":       path.name,
        "keyword":    keyword,
        "word_count": word_count,
        "issues":     issues,
        "score":      max(0, 10 - len(issues) * 2),
        "meta":       meta,
    }


def fix_em_dashes(text: str) -> str:
    text = text.replace("\u2014", ",")
    text = text.replace(" -- ", ", ")
    return text


# ---------------------------------------------------------------------------
# Auto-fix with Gemini
# ---------------------------------------------------------------------------

def ai_fix(article_path: Path, issues: list, client) -> bool:
    from google.genai import types

    text     = article_path.read_text(encoding="utf-8")
    problems = ", ".join(issues)

    prompt = f"""You are an editorial assistant. The following article has these issues: {problems}

Fix ONLY the listed issues. Do not rewrite the whole article. Return the complete fixed article in the same markdown format.

Issues to fix:
{"- Remove all em dashes (—) and replace with commas or rewrite the sentence" if "contains_em_dash" in issues else ""}
{"- Add a direct 40-60 word answer paragraph immediately after the first H2 heading (for Google featured snippets)" if "no_featured_snippet_paragraph" in issues else ""}
{"- Add or improve the meta description in the frontmatter (under 155 chars, includes keyword)" if "missing_meta_description" in issues else ""}

Article:
{text[:4000]}
"""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=4000,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        fixed = response.text
        if fixed and len(fixed) > 200:
            article_path.write_text(fixed, encoding="utf-8")
            return True
    except Exception as e:
        print(f"    AI fix failed: {e}")
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(fix: bool = False, report_only: bool = False):
    print(f"Editorial review: {ARTICLES_DIR}")
    print("=" * 60)

    md_files = list(ARTICLES_DIR.glob("*.md"))
    if not md_files:
        print("No articles found.")
        return

    results  = []
    issues_total = 0
    fixed_count  = 0

    client = None
    if fix:
        from google import genai
        api_key = os.environ.get("GEMINI_API_KEY", "")
        client  = genai.Client(api_key=api_key)

    # Check for duplicate keywords
    seen_keywords = {}
    for path in md_files:
        text = path.read_text(encoding="utf-8")
        if text.startswith("---"):
            end = text.index("---", 3)
            for line in text[3:end].strip().splitlines():
                if line.startswith("keyword:"):
                    kw = line.partition(":")[2].strip()
                    if kw in seen_keywords:
                        print(f"DUPLICATE: '{kw}' in {path.name} and {seen_keywords[kw]}")
                    else:
                        seen_keywords[kw] = path.name

    for path in sorted(md_files):
        result = check_article(path)
        results.append(result)
        issues_total += len(result["issues"])

        status = "OK" if not result["issues"] else f"{len(result['issues'])} issues"
        print(f"  [{result['score']:2d}/10] {path.stem[:45]:<45} {result['word_count']:4d}w  {status}")

        if result["issues"]:
            for issue in result["issues"]:
                print(f"          - {issue}")

            # Quick fixes that don't need AI
            if not report_only:
                text = path.read_text(encoding="utf-8")
                original = text
                if "contains_em_dash" in result["issues"]:
                    text = fix_em_dashes(text)
                if text != original:
                    path.write_text(text, encoding="utf-8")
                    print(f"          FIXED: em dashes removed")
                    fixed_count += 1

            # AI fixes for more complex issues
            if fix and client and any(i in result["issues"] for i in ["no_featured_snippet_paragraph", "missing_meta_description"]):
                print(f"          Running AI fix...")
                if ai_fix(path, result["issues"], client):
                    print(f"          FIXED: AI improvements applied")
                    fixed_count += 1

    # Save report
    report = {
        "date":         datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total":        len(results),
        "issues_found": issues_total,
        "fixed":        fixed_count,
        "articles":     results,
    }
    REPORT_FILE.write_text(json.dumps(report, indent=2))

    print(f"\n{'='*60}")
    print(f"Total articles: {len(results)}")
    print(f"Issues found:   {issues_total}")
    print(f"Fixed:          {fixed_count}")
    avg_score = sum(r["score"] for r in results) / len(results) if results else 0
    print(f"Average score:  {avg_score:.1f}/10")
    print(f"Report saved:   {REPORT_FILE}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fix",    action="store_true", help="Auto-fix issues with Gemini")
    parser.add_argument("--report", action="store_true", help="Report only, no changes")
    args = parser.parse_args()
    run(fix=args.fix, report_only=args.report)
