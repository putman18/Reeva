"""
clip_tracker.py

SQLite database for tracking clips, uploads, views, and earnings.

Tables:
  clips    - every processed clip (source, campaign/client, status)
  uploads  - upload URLs per platform per clip
  earnings - manual Vyro/ClipFarm earnings entries

Usage:
    python clipping/execution/clip_tracker.py --report weekly
    python clipping/execution/clip_tracker.py --add-clip clip.mp4 --campaign vyro-mrbeast
    python clipping/execution/clip_tracker.py --add-upload clip.mp4 --platform youtube --url https://...
    python clipping/execution/clip_tracker.py --add-earning --amount 42.50 --source vyro --note "week of Apr 7"
    python clipping/execution/clip_tracker.py --list-clips
"""

import argparse
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH      = PROJECT_ROOT / ".tmp" / "clipping" / "tracker.db"


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS clips (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        filename    TEXT NOT NULL,
        source_url  TEXT,
        campaign    TEXT,
        client      TEXT,
        created_at  TEXT DEFAULT (datetime('now')),
        status      TEXT DEFAULT 'processed'
    );

    CREATE TABLE IF NOT EXISTS uploads (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        clip_id     INTEGER REFERENCES clips(id),
        platform    TEXT NOT NULL,
        url         TEXT NOT NULL,
        uploaded_at TEXT DEFAULT (datetime('now')),
        views       INTEGER DEFAULT 0,
        views_updated_at TEXT
    );

    CREATE TABLE IF NOT EXISTS earnings (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        amount      REAL NOT NULL,
        source      TEXT NOT NULL,
        note        TEXT,
        earned_at   TEXT DEFAULT (datetime('now'))
    );
    """)
    conn.commit()


def add_clip(conn, filename: str, source_url: str = None, campaign: str = None, client: str = None) -> int:
    cur = conn.execute(
        "INSERT INTO clips (filename, source_url, campaign, client) VALUES (?, ?, ?, ?)",
        (filename, source_url, campaign, client)
    )
    conn.commit()
    return cur.lastrowid


def add_upload(conn, filename: str, platform: str, url: str) -> bool:
    row = conn.execute("SELECT id FROM clips WHERE filename = ? ORDER BY id DESC LIMIT 1", (filename,)).fetchone()
    if not row:
        print(f"Clip not found in DB: {filename}. Add it first with --add-clip.")
        return False
    conn.execute(
        "INSERT INTO uploads (clip_id, platform, url) VALUES (?, ?, ?)",
        (row["id"], platform, url)
    )
    conn.commit()
    return True


def add_earning(conn, amount: float, source: str, note: str = None):
    conn.execute(
        "INSERT INTO earnings (amount, source, note) VALUES (?, ?, ?)",
        (amount, source, note)
    )
    conn.commit()


def weekly_report(conn):
    since = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    clips_total = conn.execute("SELECT COUNT(*) FROM clips").fetchone()[0]
    clips_week  = conn.execute("SELECT COUNT(*) FROM clips WHERE created_at >= ?", (since,)).fetchone()[0]

    uploads_total = conn.execute("SELECT COUNT(*) FROM uploads").fetchone()[0]
    uploads_week  = conn.execute("SELECT COUNT(*) FROM uploads WHERE uploaded_at >= ?", (since,)).fetchone()[0]

    views_total = conn.execute("SELECT COALESCE(SUM(views), 0) FROM uploads").fetchone()[0]
    views_week  = conn.execute("SELECT COALESCE(SUM(views), 0) FROM uploads WHERE uploaded_at >= ?", (since,)).fetchone()[0]

    earnings_total = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM earnings").fetchone()[0]
    earnings_week  = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM earnings WHERE earned_at >= ?", (since,)).fetchone()[0]

    by_platform = conn.execute("""
        SELECT platform, COUNT(*) as cnt, COALESCE(SUM(views), 0) as total_views
        FROM uploads GROUP BY platform ORDER BY cnt DESC
    """).fetchall()

    recent_earnings = conn.execute("""
        SELECT amount, source, note, earned_at FROM earnings ORDER BY earned_at DESC LIMIT 5
    """).fetchall()

    print("=" * 50)
    print("  CLIPPING TRACKER - WEEKLY REPORT")
    print("=" * 50)
    print(f"  Clips processed:   {clips_week} this week  ({clips_total} total)")
    print(f"  Uploads posted:    {uploads_week} this week  ({uploads_total} total)")
    print(f"  Views:             {views_week:,} this week  ({views_total:,} total)")
    print(f"  Earnings:          ${earnings_week:.2f} this week  (${earnings_total:.2f} total)")
    print()

    if by_platform:
        print("  By platform:")
        for row in by_platform:
            print(f"    {row['platform']:12s} {row['cnt']} clips   {row['total_views']:,} views")
        print()

    if recent_earnings:
        print("  Recent earnings:")
        for row in recent_earnings:
            note = f"  ({row['note']})" if row['note'] else ""
            print(f"    ${row['amount']:.2f} from {row['source']}{note}  [{row['earned_at'][:10]}]")

    # Vyro estimate: $3 per 1,000 views
    if views_total > 0:
        vyro_estimate = views_total / 1000 * 3
        print(f"\n  Vyro estimate (at $3/1K views): ${vyro_estimate:.2f}")
    print("=" * 50)


def list_clips(conn):
    rows = conn.execute("""
        SELECT c.id, c.filename, c.campaign, c.client, c.created_at,
               COUNT(u.id) as upload_count,
               COALESCE(SUM(u.views), 0) as total_views
        FROM clips c
        LEFT JOIN uploads u ON u.clip_id = c.id
        GROUP BY c.id
        ORDER BY c.created_at DESC
        LIMIT 20
    """).fetchall()

    print(f"{'ID':>4}  {'Filename':<45}  {'Campaign/Client':<20}  {'Uploads':>7}  {'Views':>8}  Date")
    print("-" * 110)
    for r in rows:
        tag = r["campaign"] or r["client"] or ""
        print(f"{r['id']:>4}  {r['filename'][:45]:<45}  {tag[:20]:<20}  {r['upload_count']:>7}  {r['total_views']:>8}  {r['created_at'][:10]}")


def main():
    parser = argparse.ArgumentParser(description="Track clips, uploads, and earnings")
    parser.add_argument("--report",      action="store_true", help="Show weekly report")
    parser.add_argument("--list-clips",  action="store_true", help="List recent clips")
    parser.add_argument("--add-clip",    metavar="FILENAME",  help="Register a clip in the DB")
    parser.add_argument("--source-url",  default=None,        help="Source VOD URL (with --add-clip)")
    parser.add_argument("--campaign",    default=None,        help="Campaign name e.g. vyro-mrbeast")
    parser.add_argument("--client",      default=None,        help="Client slug e.g. ninja-clips")
    parser.add_argument("--add-upload",  metavar="FILENAME",  help="Register an upload URL for a clip")
    parser.add_argument("--platform",    default=None,        help="Platform (youtube, twitter, tiktok)")
    parser.add_argument("--url",         default=None,        help="Upload URL")
    parser.add_argument("--add-earning", action="store_true", help="Log an earning")
    parser.add_argument("--amount",      type=float,          help="Earning amount in $")
    parser.add_argument("--source",      default="vyro",      help="Earning source (vyro, clipfarm, client)")
    parser.add_argument("--note",        default=None,        help="Note for the earning")
    args = parser.parse_args()

    conn = get_conn()
    init_db(conn)

    if args.add_clip:
        clip_id = add_clip(conn, args.add_clip, args.source_url, args.campaign, args.client)
        print(f"Added clip ID {clip_id}: {args.add_clip}")

    elif args.add_upload:
        if not args.platform or not args.url:
            print("--add-upload requires --platform and --url")
        else:
            ok = add_upload(conn, args.add_upload, args.platform, args.url)
            if ok:
                print(f"Recorded upload: {args.add_upload} -> {args.platform}: {args.url}")

    elif args.add_earning:
        if not args.amount:
            print("--add-earning requires --amount")
        else:
            add_earning(conn, args.amount, args.source, args.note)
            print(f"Recorded earning: ${args.amount:.2f} from {args.source}")

    elif args.list_clips:
        list_clips(conn)

    else:
        weekly_report(conn)

    conn.close()


if __name__ == "__main__":
    main()
