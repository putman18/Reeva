"""
clip_setup.py

Installs and verifies all dependencies for the clipping pipeline.
Run this once before using any other clipping scripts.

Usage:
    python clipping/execution/clip_setup.py
"""

import subprocess
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent


def run(cmd, desc):
    print(f"  {desc}...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  FAILED: {result.stderr.strip()}")
        return False
    print(f"  OK")
    return True


def check_binary(name):
    path = shutil.which(name)
    if path:
        print(f"  {name}: found at {path}")
        return True
    print(f"  {name}: NOT FOUND")
    return False


def main():
    print("=== Clipping Pipeline Setup ===\n")

    # Python packages
    print("Installing Python packages...")
    packages = ["yt-dlp", "librosa", "faster-whisper", "numpy", "requests"]
    for pkg in packages:
        run([sys.executable, "-m", "pip", "install", pkg, "-q"], f"pip install {pkg}")

    print("\nChecking system binaries...")
    ffmpeg_ok = check_binary("ffmpeg")
    ffprobe_ok = check_binary("ffprobe")

    if not ffmpeg_ok or not ffprobe_ok:
        print("\nffmpeg not found. Install it:")
        print("  Windows: winget install ffmpeg")
        print("  Or download from https://ffmpeg.org/download.html")
        print("  Then restart your terminal.\n")
    else:
        # Check ffmpeg version
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
        version_line = result.stdout.split("\n")[0]
        print(f"  ffmpeg version: {version_line}")

    print("\nChecking .env keys...")
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        env_text = env_path.read_text()
        keys_to_check = ["GOOGLE_CREDENTIALS_FILE", "GOOGLE_TOKEN_FILE"]
        for key in keys_to_check:
            status = "found" if key in env_text else "MISSING"
            print(f"  {key}: {status}")
    else:
        print("  .env not found at project root")

    print("\nChecking tmp folders...")
    for folder in ["raw", "segments", "processed"]:
        path = PROJECT_ROOT / ".tmp" / "clipping" / folder
        path.mkdir(parents=True, exist_ok=True)
        print(f"  .tmp/clipping/{folder}: OK")

    print("\n=== Setup complete ===")
    if not ffmpeg_ok:
        print("ACTION NEEDED: Install ffmpeg before using clip_processor.py")


if __name__ == "__main__":
    main()
