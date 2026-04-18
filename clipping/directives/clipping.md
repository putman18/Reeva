# Clipping Pipeline Directive

## What This Is
Automated pipeline for gaming/streamer clip content. Two revenue paths:
1. **Vyro/ClipFarm campaigns** - Post clips of big creators (MrBeast etc.) to your accounts, earn $3/1,000 views. No audience needed.
2. **Streamer client service** - $500-1,500/month per streamer, pipeline handles delivery.

## Quick Start Commands

```bash
# Full Vyro pipeline (download -> process -> upload -> log)
python clipping/execution/clip_pipeline.py --mode vyro --url <clip_url> --title "insane play" --platforms youtube,twitter

# Full streamer VOD pipeline (download -> detect -> process -> save for review)
python clipping/execution/clip_pipeline.py --mode streamer --url <vod_url> --client <client-slug>

# Process a local file only
python clipping/execution/clip_pipeline.py --mode process --file clip.mp4 --title "clutch"

# Weekly earnings report
python clipping/execution/clip_tracker.py --report

# Log a Vyro payout
python clipping/execution/clip_tracker.py --add-earning --amount 87.50 --source vyro --note "week of Apr 7"
```

## Step-by-Step Setup

### 1. Install dependencies (one-time)
```bash
python clipping/execution/clip_setup.py
winget install ffmpeg   # restart terminal after
```

### 2. Sign up for Vyro
- Go to vyro.ai, create account
- Join an active campaign (MrBeast, Mark Rober, etc.)
- They provide pre-cut clip URLs
- You post to your TikTok/YouTube/Instagram
- Submit your post URLs back to Vyro for view tracking
- Paid out roughly weekly

### 3. Set up YouTube upload (one-time)
- Google credentials already in .env (GOOGLE_CREDENTIALS_FILE)
- First upload will open browser for OAuth consent
- After that, uploads are automatic

### 4. Set up X (Twitter) upload (one-time)
Add to `.env`:
```
TWITTER_API_KEY=...
TWITTER_API_SECRET=...
TWITTER_ACCESS_TOKEN=...
TWITTER_ACCESS_TOKEN_SECRET=...
```
Get keys free at developer.twitter.com (Basic tier, free)

### 5. TikTok (manual for now)
- Pipeline saves processed clips to `.tmp/clipping/processed/`
- Upload manually to TikTok (5 min/day)
- OR use Buffer ($15/month) to schedule TikTok posts

## Daily Workflow (Vyro path)

1. Get today's campaign clip URL from Vyro dashboard
2. Run pipeline:
   ```bash
   python clipping/execution/clip_pipeline.py --mode vyro --url <url> --title "title" --platforms youtube,twitter
   ```
3. Upload processed clip to TikTok manually (`.tmp/clipping/processed/`)
4. Submit YouTube + X URLs to Vyro dashboard
5. Log any payouts received: `python clipping/execution/clip_tracker.py --add-earning --amount X --source vyro`

Target: 4-5 clips/day = 30+ clips/week in circulation

## Streamer Client Workflow

1. Client signs contract, pays first month upfront via Stripe
2. Create client folder: `clipping/clients/<slug>/brief.md`
3. Get VOD URL from their Twitch/YouTube channel
4. Run streamer pipeline:
   ```bash
   python clipping/execution/clip_pipeline.py --mode streamer --url <vod_url> --client <slug>
   ```
5. Review clips in `clipping/clients/<slug>/clips/`
6. Upload to their accounts (they share credentials) or deliver files via Google Drive

## Revenue Tracking

Views and earnings are logged in `.tmp/clipping/tracker.db`

Run weekly report: `python clipping/execution/clip_tracker.py --report`

Vyro pays ~$3 per 1,000 views. To hit $300/day = 100,000 views/day across all platforms.
With 4-5 clips/day at average 10K views each = 40-50K views/day by month 2.

## File Structure

```
.tmp/clipping/
  raw/         - downloaded VODs/clips (safe to delete after processing)
  segments/    - extracted highlight segments (intermediate)
  processed/   - final 1080x1920 vertical clips ready to post
  tracker.db   - SQLite database of all clips, uploads, earnings

clipping/clients/
  <client-slug>/
    brief.md   - streamer info, game, schedule, delivery format
    clips/     - processed clips for this client
```

## Known Constraints

- **TikTok**: No public API for personal accounts. Upload manually or use Buffer ($15/mo).
- **Instagram Reels**: Requires Facebook Business account + Graph API approval. Add later.
- **Twitch VODs**: Some streamers set VODs to expire after 14-60 days. Download promptly.
- **Music in clips**: Clips with copyrighted background music will get muted on YouTube (Content ID). Clip moments with game audio only, or replace with royalty-free music.
- **Nintendo content**: Nintendo is aggressive with copyright claims. Avoid Nintendo game clips for monetized channels.
- **Vyro payout**: Roughly weekly, view count must be verified. Keep all post URLs logged.
