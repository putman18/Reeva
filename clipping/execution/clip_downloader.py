"""
clip_downloader.py

Downloads clips and VODs from Twitch, YouTube, and 1,000+ other sites using yt-dlp.

Usage:
    python clipping/execution/clip_downloader.py --url <url>
    python clipping/execution/clip_downloader.py --url <url> --out .tmp/clipping/raw/
    python clipping/execution/clip_downloader.py --url <url> --quality 720  # limit quality
"""

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
DEFAULT_OUT   = PROJECT_ROOT / ".tmp" / "clipping" / "raw"


def download(url: str, out_dir: Path, quality: int = 1080) -> Path:
    """
    Download a video from any yt-dlp-supported URL.
    Returns the path of the downloaded file.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    # Output template: use video title, sanitised
    output_template = str(out_dir / "%(title).60s.%(ext)s")

    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--format", f"bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]/best[height<={quality}][ext=mp4]/best",
        "--merge-output-format", "mp4",
        "--output", output_template,
        "--no-playlist",           # single video only, not whole channel
        "--no-warnings",
        "--progress",
        url,
    ]

    print(f"Downloading: {url}")
    print(f"Output dir:  {out_dir}")

    result = subprocess.run(cmd, capture_output=False)

    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed with exit code {result.returncode}")

    # Find the most recently modified mp4 in the output folder
    mp4_files = sorted(out_dir.glob("*.mp4"), key=lambda f: f.stat().st_mtime)
    if not mp4_files:
        raise RuntimeError(f"Download appeared to succeed but no .mp4 found in {out_dir}")

    downloaded = mp4_files[-1]
    print(f"\nSaved to: {downloaded}")
    return downloaded


def main():
    parser = argparse.ArgumentParser(description="Download a clip or VOD")
    parser.add_argument("--url",     required=True, help="URL to download (Twitch, YouTube, etc.)")
    parser.add_argument("--out",     default=str(DEFAULT_OUT), help="Output directory")
    parser.add_argument("--quality", type=int, default=1080, help="Max video height (default 1080)")
    args = parser.parse_args()

    out_dir = Path(args.out)
    path = download(args.url, out_dir, args.quality)
    print(f"\nReady for processing: {path.name}")


if __name__ == "__main__":
    main()
