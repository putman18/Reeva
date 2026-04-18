"""
deploy.py

Builds the site and pushes to GitHub (auto-deploys to Cloudflare Pages).

Usage:
    python shared/execution/deploy.py
"""

import subprocess
import sys
from pathlib import Path

ADVERT_ROOT = Path(__file__).parent.parent.parent
DIST_DIR    = ADVERT_ROOT / "finance" / "site" / "dist"
REMOTE_URL  = "https://github.com/putman18/thefinanceblueprint.git"


def run(cmd, cwd=None):
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.returncode != 0 and result.stderr.strip():
        print(result.stderr.strip())
    return result.returncode == 0


def deploy(message="Update site"):
    print("Building site...")
    ok = run([sys.executable, "shared/execution/site_builder.py"], cwd=ADVERT_ROOT)
    if not ok:
        print("Build failed.")
        return

    git_dir = DIST_DIR / ".git"
    if not git_dir.exists():
        print("Initializing git repo in dist...")
        run(["git", "init"], cwd=DIST_DIR)
        run(["git", "remote", "add", "origin", REMOTE_URL], cwd=DIST_DIR)

    run(["git", "add", "-A"], cwd=DIST_DIR)
    run(["git", "commit", "-m", message], cwd=DIST_DIR)
    run(["git", "branch", "-M", "main"], cwd=DIST_DIR)
    run(["git", "push", "-u", "origin", "main", "--force"], cwd=DIST_DIR)
    print("\nDeployed. Cloudflare will update in ~60 seconds.")


if __name__ == "__main__":
    msg = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Update site"
    deploy(msg)
