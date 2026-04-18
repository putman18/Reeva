"""
clip_pipeline.py

Main orchestrator. Runs the full clipping pipeline end-to-end.

Modes:
  vyro      - Download Vyro campaign clip, process, upload to YouTube + X, log
  streamer  - Download full VOD, detect highlights, process, save for review
  process   - Skip download, process a local file directly

Usage:
    # Vyro campaign (fastest path to money)
    python clipping/execution/clip_pipeline.py --url https://... --mode vyro --title "insane play"

    # Streamer client VOD
    python clipping/execution/clip_pipeline.py --url https://twitch.tv/videos/... --mode streamer --client ninja-clips

    # Process an already-downloaded file
    python clipping/execution/clip_pipeline.py --file .tmp/clipping/raw/clip.mp4 --mode process --title "clutch"

    # Batch: process all raw mp4s in the folder
    python clipping/execution/clip_pipeline.py --mode process --batch
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(Path(__file__).parent))

from clip_downloader import download
from clip_processor  import process_clip
from clip_detector   import detect
from clip_uploader   import upload
from clip_tracker    import get_conn, init_db, add_clip, add_upload

RAW_DIR       = PROJECT_ROOT / ".tmp" / "clipping" / "raw"
SEGMENTS_DIR  = PROJECT_ROOT / ".tmp" / "clipping" / "segments"
PROCESSED_DIR = PROJECT_ROOT / ".tmp" / "clipping" / "processed"


def run_vyro(url: str, title: str, platforms: list, campaign: str = "vyro"):
    """Download a Vyro campaign clip, process it, upload, and log."""
    print(f"\n=== VYRO MODE ===")
    print(f"Campaign: {campaign}")

    # 1. Download
    raw_path = download(url, RAW_DIR)

    # 2. Process (full clip, no trimming)
    print("\nProcessing clip...")
    processed_path = process_clip(raw_path, PROCESSED_DIR, captions=True, slug=title[:40].replace(" ", "-"))

    # 3. Upload
    print(f"\nUploading to: {platforms}")
    results = upload(processed_path, title, platforms=platforms)

    # 4. Log to tracker
    conn = get_conn()
    init_db(conn)
    clip_id = add_clip(conn, processed_path.name, source_url=url, campaign=campaign)
    for platform, upload_url in results.items():
        add_upload(conn, processed_path.name, platform, upload_url)
    conn.close()

    print(f"\n=== Done ===")
    print(f"Clip: {processed_path.name}")
    for platform, upload_url in results.items():
        print(f"  {platform}: {upload_url}")
    print(f"\nSubmit these URLs to Vyro/ClipFarm dashboard to track views.")


def run_streamer(url: str, client: str, top_n: int = 8, platforms: list = None):
    """Download a streamer VOD, detect highlights, process, save for manual review."""
    print(f"\n=== STREAMER MODE ===")
    print(f"Client: {client}")

    client_dir = PROJECT_ROOT / "clipping" / "clients" / client / "clips"
    client_dir.mkdir(parents=True, exist_ok=True)

    # 1. Download full VOD
    raw_path = download(url, RAW_DIR)

    # 2. Detect highlights
    print("\nDetecting highlights...")
    segment_paths = detect(raw_path, SEGMENTS_DIR, top_n=top_n)

    if not segment_paths:
        print("No highlights detected. Try lowering the detection threshold.")
        return

    # 3. Process each segment
    print(f"\nProcessing {len(segment_paths)} segments...")
    processed = []
    for seg_path in segment_paths:
        out = process_clip(seg_path, client_dir, captions=True)
        processed.append(out)

    # 4. Log to tracker
    conn = get_conn()
    init_db(conn)
    for p in processed:
        add_clip(conn, p.name, source_url=url, client=client)
    conn.close()

    print(f"\n=== Done ===")
    print(f"{len(processed)} clips saved to: {client_dir}")
    print("Review clips, then upload manually or run:")
    print(f"  python clipping/execution/clip_uploader.py --clip <path> --title '...' --platforms youtube,twitter")


def run_process(file_path: Path, title: str, platforms: list, campaign: str = None, batch: bool = False):
    """Process a local file (or batch folder) and optionally upload."""
    print(f"\n=== PROCESS MODE ===")

    if batch:
        mp4_files = sorted(file_path.glob("*.mp4")) if file_path.is_dir() else [file_path]
        print(f"Batch: {len(mp4_files)} files")
        for f in mp4_files:
            print(f"\nProcessing: {f.name}")
            out = process_clip(f, PROCESSED_DIR, captions=True)
            if platforms:
                t = title or f.stem[:50]
                results = upload(out, t, platforms=platforms)
                conn = get_conn()
                init_db(conn)
                add_clip(conn, out.name, campaign=campaign)
                for platform, url in results.items():
                    add_upload(conn, out.name, platform, url)
                conn.close()
    else:
        out = process_clip(file_path, PROCESSED_DIR, captions=True, slug=(title or file_path.stem)[:40])
        if platforms:
            results = upload(out, title or file_path.stem, platforms=platforms)
            conn = get_conn()
            init_db(conn)
            add_clip(conn, out.name, campaign=campaign)
            for platform, url in results.items():
                add_upload(conn, out.name, platform, url)
            conn.close()
            for platform, url in results.items():
                print(f"  {platform}: {url}")

    print("\nDone.")


def main():
    parser = argparse.ArgumentParser(description="Clipping pipeline orchestrator")
    parser.add_argument("--mode",      choices=["vyro", "streamer", "process"], default="process")
    parser.add_argument("--url",       help="Source URL (Twitch/YouTube VOD or Vyro clip link)")
    parser.add_argument("--file",      help="Local video file path (for process mode)")
    parser.add_argument("--title",     default="", help="Title/caption for the clip")
    parser.add_argument("--client",    help="Client slug (streamer mode)")
    parser.add_argument("--campaign",  default="vyro", help="Campaign name (vyro mode)")
    parser.add_argument("--platforms", default="youtube", help="Upload platforms: youtube,twitter")
    parser.add_argument("--top",       type=int, default=8, help="Number of highlights (streamer mode)")
    parser.add_argument("--batch",     action="store_true", help="Batch process all files in --file folder")
    args = parser.parse_args()

    platforms = [p.strip().lower() for p in args.platforms.split(",") if p.strip()]

    if args.mode == "vyro":
        if not args.url:
            print("--url required for vyro mode")
            sys.exit(1)
        run_vyro(args.url, args.title, platforms, args.campaign)

    elif args.mode == "streamer":
        if not args.url or not args.client:
            print("--url and --client required for streamer mode")
            sys.exit(1)
        run_streamer(args.url, args.client, args.top, platforms if platforms != ["youtube"] else None)

    elif args.mode == "process":
        file_path = Path(args.file) if args.file else RAW_DIR
        run_process(file_path, args.title, platforms if args.platforms != "youtube" else [], args.campaign, args.batch)


if __name__ == "__main__":
    main()
