# Projects Workspace

This file extends the global agent instructions in `~/.claude/CLAUDE.md` with workspace-specific layout and active projects.

## Directory Structure

```
Projects/
├── CLAUDE.md                    # This file
├── .env                         # All API keys and secrets (shared across projects)
├── .gitignore
├── .tmp/                        # All intermediate files - never commit, always regenerated
│
├── crypto/                      # Crypto trading project
│   ├── directives/
│   │   └── crypto_trading.md    # Master directive for the trading system
│   ├── execution/
│   │   ├── crypto_setup.py      # Phase 1: install Freqtrade
│   │   ├── crypto_backtest.py   # Phase 2: backtest strategy
│   │   ├── crypto_paper_trade.py # Phase 3: paper trading
│   │   ├── crypto_live.py       # Phase 4: live trading
│   │   ├── crypto_download_data.py
│   │   ├── crypto_fetch_signals.py
│   │   ├── crypto_hourly_update.py
│   │   └── crypto_report.py
│   └── freqtrade-config/        # Freqtrade configs and strategy
│       ├── config_paper.json
│       ├── config_live.json
│       └── strategies/
│           └── RSI_MA_Strategy.py
│
├── blackjack/                   # Blackjack Martingale bot project
│   ├── directives/
│   │   └── blackjack_martingale.md
│   └── execution/
│       └── blackjack_bot.py     # Playwright bot for 247blackjack.com
│
└── shared/                      # Shared tools used across projects
    ├── directives/
    │   └── add_webhook.md
    └── execution/
        ├── discord_bot.py       # Send messages, create channels in Discord
        ├── webhook_server.py    # Local webhook server (replaces Modal)
        ├── send_email.py
        ├── read_sheet.py
        ├── update_sheet.py
        ├── webhooks.json
        └── requirements.txt
```

**Key principles:**
- `.env` lives at the workspace root and is shared by all projects
- `.tmp/` lives at the workspace root - all intermediate files go here
- Each project is self-contained in its own folder
- `shared/` contains tools used by multiple projects

## Path conventions for scripts

Scripts resolve paths relative to their location:
- Crypto scripts: `CRYPTO_ROOT = Path(__file__).parent.parent` (= `Projects/crypto/`)
- Crypto scripts: `PROJECT_ROOT = CRYPTO_ROOT.parent` (= `Projects/`)
- Blackjack scripts: `PROJECT_ROOT = Path(__file__).parent.parent.parent` (= `Projects/`)
- `.env` is always at `PROJECT_ROOT / ".env"`
- `.tmp/` is always at `PROJECT_ROOT / ".tmp"`

## Active Projects

### Crypto Trading (Phase 3 - Paper Trading)
- Exchange: Coinbase Advanced Trade (NY-legal)
- Strategy: EMA20/50 crossover + SMA200 + ADX > 20 + RSI > 50 (v6)
- Pairs: BTC/USD, ETH/USD, XRP/USD
- Paper trading running: start with `python crypto/execution/crypto_paper_trade.py --start`
- Backtest passed all gates on 2026-04-02
- Fee note: set to 0.1% for testing (Coinbase actual fees ~0.5% are too high for this strategy's thin margins)

### Blackjack Martingale Bot (In Development)
- Site: 247blackjack.com
- Strategy: Martingale (double after loss, reset after win)
- Daily goal: $300 profit then stop
- Base bet: $5, max bet: $640
- Run with: `python blackjack/execution/blackjack_bot.py`

## Webhooks (Local Server)

**When user says "add a webhook that...":**
1. Read `shared/directives/add_webhook.md` for complete instructions
2. Create the directive file in the relevant project's `directives/`
3. Add entry to `shared/execution/webhooks.json`
4. Start server: `python shared/execution/webhook_server.py`
5. Test: `curl -X POST http://localhost:8000/<slug> -d '{...}'`

## n8n Workflows

**IMPORTANT: Use the n8n REST API, not MCP tools.**

The n8n MCP server has limitations (incomplete workflow listings, unreliable search). Always use the Python execution script for n8n operations.

Script: `shared/execution/create_n8n_workflow.py` - if it does not exist, create it before proceeding.

**Commands:**
- List workflows: `python shared/execution/create_n8n_workflow.py --list-workflows`
- Get workflow: `python shared/execution/create_n8n_workflow.py --get-workflow <ID>`
- Create workflow: `python shared/execution/create_n8n_workflow.py --name "Name" --input .tmp/workflow.json`
- Update workflow: `python shared/execution/create_n8n_workflow.py --update <ID> --input .tmp/workflow.json`
- Activate: `python shared/execution/create_n8n_workflow.py --activate <ID>`

Directive: `shared/directives/generate_n8n_workflow.md` - if it does not exist, create it.

**Required .env variables:**
- `N8N_API_URL` - Your n8n instance API URL
- `N8N_API_KEY` - API key from n8n Settings > API

## Discord

Bot is connected to the user's Discord server.
- Script: `shared/execution/discord_bot.py`
- Channels: #paper-trading (hourly updates), #alerts (kill conditions), #backtest-results
- Run hourly updates: `python crypto/execution/crypto_hourly_update.py --loop`

## Deploy Contract

No long-running process is "deployed" until ALL of these are true:

1. **Boot ping** — process emits a "started at <timestamp>" message to Discord within 60s of startup
2. **Heartbeat** — process registers with `shared/watchtower/` and emits status >= every 5min
3. **Silent-death rule** — a specific operational metric (not just process liveness) is monitored. Examples:
   - Trading bot: "trades_today < 25% of expected_daily_trades during market hours"
   - Voicebot: "calls_received in last 24h == 0 AND day is a business day"
   - Advert pipeline: "no new article published in last 26 hours"
4. **External watcher** — UptimeRobot (or equivalent) pings a health endpoint and alerts on absence. The watchdog cannot be the only watcher of itself

Trading strategies have an additional requirement BEFORE any paper-trade deploy:
- Signal frequency check on >=1 year of historical data
- Expected trades-per-week recorded as constant in the strategy file
- Backtest passing is necessary but NOT sufficient — a strategy can pass a Sharpe gate with 3 lucky trades and never trade in production

If you cannot satisfy all four monitoring requirements before launch, the deploy does not happen. Write the monitoring first, then the feature.

This rule comes from the crypto v6 incident (2026-04-03 to 2026-04-17): a strategy was deployed, the process died at some point in the first 14 days, no alert fired, and the bot had 0 trades total when finally checked. See `.tmp/postmortem_crypto_v6.md`.

## Portfolio Website

Live at: `putman18.github.io` (GitHub Pages, plain HTML + Tailwind CSS)
Repo: `putman18/portfolio`

**Projects showcased:**
- RegulatoryRAG — https://regulatoryrag-4c8gwkjqtcnqq77da6cdio.streamlit.app
- Stockbot — https://github.com/putman18/stockbot
- Voicebot — https://github.com/putman18/voicebot

**Design system (godly.website aesthetic):**
- Background: `#0a0a0a`, text: `#f0f0f0`, accent: `#4a90e2`
- Font: large display serif for hero, monospace for code/tech tags
- Full-viewport sections, scroll-triggered fade-ins
- Dark-first — no light mode toggle
- Generous whitespace: 120px+ section padding, 1.8 line-height body text
- Project cards: hover lifts with subtle border glow, tech stack pill tags
- No stock photos, no clutter, no nav links beyond name + contact

**When building/updating portfolio:**
- One `index.html` + Tailwind CDN — no build pipeline
- Keep descriptions to 2 lines max per project
- Always mobile-first (test at 375px width)

## Watchtower (shared observability service)

Located at `shared/watchtower/`. Every long-running process in this workspace registers with it.

- `notifier.py` — Discord webhook sender with rate-limit handling
- `heartbeat.py` — Tenants register with name + expected_interval + silent-death rule; watchtower tracks last-seen and fires absence alerts
- `health.py` — HTTP endpoint at `/health` for UptimeRobot to ping. Returns 200 if all registered tenants are within their expected_interval, 500 if any are stale
- Directive: `shared/directives/watchtower.md`

How to register a new tenant from any execution script:
```python
from shared.watchtower.heartbeat import register, beat
register("stocks-bot", expected_interval_secs=300, silent_death_rule="trades_today < 0.25 * expected_daily_trades during market hours")
# In your main loop:
beat("stocks-bot", status="ok", metrics={"trades_today": 3, "expected_daily_trades": 12})
```
