"""
affiliate_checker.py

Checks all affiliate links in affiliate_links.json are still valid (200 OK).
Flags dead links, redirects, and placeholder URLs.
Run this weekly to catch expired affiliate programs.

Usage:
    python shared/execution/affiliate_checker.py
"""

import json
import os
import urllib.request
import urllib.error
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

AFFILIATE_CONFIG = ADVERT_ROOT / "finance" / "directives" / "affiliate_links.json"
LOG_FILE         = PROJECT_ROOT / ".tmp" / "affiliate_check.log"


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def check_url(url: str) -> dict:
    if url.startswith("YOUR_"):
        return {"status": "placeholder", "code": None, "ok": False}
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; LinkChecker/1.0)"}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return {"status": "ok", "code": r.status, "ok": True}
    except urllib.error.HTTPError as e:
        return {"status": "http_error", "code": e.code, "ok": False}
    except urllib.error.URLError as e:
        return {"status": "connection_error", "code": None, "ok": False, "reason": str(e.reason)}
    except Exception as e:
        return {"status": "error", "code": None, "ok": False, "reason": str(e)}


def run():
    log("=" * 60)
    log("Affiliate link check starting")

    if not AFFILIATE_CONFIG.exists():
        log("ERROR: affiliate_links.json not found")
        return

    data = json.loads(AFFILIATE_CONFIG.read_text())
    programs = data["programs"]

    results = {"ok": [], "placeholder": [], "dead": []}

    for p in programs:
        name = p["name"]
        url  = p["url"]
        result = check_url(url)

        if result["status"] == "placeholder":
            log(f"  PENDING  {name} - no affiliate URL set yet")
            results["placeholder"].append(name)
        elif result["ok"]:
            log(f"  OK       {name} ({result['code']}) - {url[:60]}")
            results["ok"].append(name)
            p["status"] = "active"
            p["last_checked"] = datetime.now().strftime("%Y-%m-%d")
        else:
            log(f"  DEAD     {name} - {result['status']} {result.get('code', '')} - {url[:60]}")
            results["dead"].append(name)
            p["status"] = "dead"
            p["last_checked"] = datetime.now().strftime("%Y-%m-%d")

    # Save updated statuses back
    AFFILIATE_CONFIG.write_text(json.dumps(data, indent=2))

    log(f"\nSummary:")
    log(f"  Active:      {len(results['ok'])} programs")
    log(f"  Pending:     {len(results['placeholder'])} programs (need URL)")
    log(f"  Dead/broken: {len(results['dead'])} programs")

    if results["dead"]:
        log(f"\nACTION NEEDED - Replace these dead affiliate links:")
        for name in results["dead"]:
            log(f"  - {name}")

    if results["placeholder"]:
        log(f"\nTODO - Sign up and add URLs for:")
        for name in results["placeholder"]:
            log(f"  - {name}")


if __name__ == "__main__":
    run()
