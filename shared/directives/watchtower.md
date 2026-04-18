# Watchtower

Shared observability layer for every long-running process in this workspace.

Born out of the crypto v6 incident (April 3-17, 2026): a paper trading bot ran for 14 days, made 0 trades, and the process was dead for an unknown portion of that time. No alert ever fired. See `.tmp/postmortem_crypto_v6.md`.

## What it is

Three pieces in `shared/watchtower/`:

- **`notifier.py`** — Discord webhook sender with rate-limit handling (25/min cap, exponential backoff on 429)
- **`heartbeat.py`** — SQLite-backed tenant registry. Tenants register with name + expected interval + operational rule. Sends boot pings on register, silent-death alerts when a tenant misses its window, operational-failure alerts when a tenant is alive but breaking its rule
- **`health.py`** — HTTP endpoint at `/health` for an external pinger (UptimeRobot). Returns 200 if all tenants are within their expected interval, 503 if any are stale

## The three failure modes it catches

1. **Process death** — heartbeat stops arriving, watchtower fires `silent_death_alert`
2. **Operational death** — process alive but doing the wrong thing (e.g., trading bot up but 0 trades when 12 expected). Watchtower fires `operational_failure_alert` when a caller-supplied rule_evaluator returns violated=True
3. **Watchtower itself dies** — UptimeRobot stops getting 200s from `/health` and pages the user. The watcher of the watcher

## How to register a tenant

From any execution script in the workspace:

```python
from shared.watchtower.heartbeat import register, beat

register(
    "stocks-bot",
    expected_interval_secs=300,  # beat at least every 5 min
    silent_death_rule="trades_today < 0.25 * expected_daily_trades during market hours",
)

# In your main loop:
while True:
    do_work()
    beat("stocks-bot", status="ok", metrics={
        "trades_today": current_trade_count,
        "expected_daily_trades": 12,
    })
    time.sleep(60)
```

`register()` fires the boot ping. `beat()` updates last-seen and metrics.

## How to evaluate operational rules

The watchtower stores the rule string but does not interpret it (rules are tenant-specific and require domain logic like NYSE market calendars). Each tenant project provides a `rule_evaluator` callable that the watchtower invokes.

Example for a stocks bot:

```python
import pandas_market_calendars as mcal
from datetime import datetime
from shared.watchtower.heartbeat import evaluate_operational_failures

NYSE = mcal.get_calendar("NYSE")

def stocks_rule(tenant: dict, metrics: dict) -> tuple[bool, str]:
    now = datetime.now()
    schedule = NYSE.schedule(start_date=now.date(), end_date=now.date())
    if schedule.empty:
        return (False, "market closed today")
    expected = metrics.get("expected_daily_trades", 0)
    actual = metrics.get("trades_today", 0)
    if actual < 0.25 * expected:
        return (True, f"trades_today={actual} < 25% of expected={expected}")
    return (False, "ok")

evaluate_operational_failures(stocks_rule)
```

## How to run the watchtower itself

Two processes need to be running on the deploy target:

```bash
# 1. The watchtower loop — checks for silent deaths every 60s
python -m shared.watchtower.heartbeat loop 60

# 2. The health endpoint — UptimeRobot pings this every 5 min
python -m shared.watchtower.health 8765
```

Both should be daemonized (systemd on Hostinger). The health endpoint must be reachable from the public internet for UptimeRobot to ping it (open port 8765 in the firewall, or proxy via nginx).

## Deploy Contract requirements (from `CLAUDE.md`)

Before any long-running process is considered "deployed":

1. **Boot ping** — `register()` fires this automatically
2. **Heartbeat** — caller must `beat()` at least every `expected_interval_secs`
3. **Silent-death rule** — caller must define the operational rule and provide a `rule_evaluator`
4. **External watcher** — UptimeRobot pinging `http://<server>:8765/health` every 5 min, alerting on absence

## UptimeRobot setup

1. Sign up at https://uptimerobot.com (free tier: 50 monitors, 5-min intervals)
2. Add new monitor:
   - Type: HTTP(s)
   - URL: `http://<your-hostinger-ip>:8765/health`
   - Interval: 5 minutes
   - Alert contact: SMS or email or Discord webhook
3. Add a second monitor (the heartbeat-of-the-heartbeat):
   - URL: `http://<your-hostinger-ip>:8765/tenants`
   - Same interval

## Edgecases this design catches (from chatroom postmortem)

- **Cold-start typo**: register() fires the boot ping immediately. If the URL is wrong or the .env is missing, no boot ping arrives and you know within 60s
- **DST and weekends**: not handled by watchtower — handled by the caller's rule_evaluator (which uses pandas_market_calendars or similar)
- **Discord rate limits**: notifier.py caps sends at 25/min per webhook with exponential backoff on 429
- **Webhook archive/rotate**: when a webhook URL stops working, notifier.send() returns False and prints to stderr. Caller can detect repeated False returns and escalate. (TODO: add fallback notification path — email or SMS — for when Discord is down)
- **Watchtower watching itself**: the watchtower self-registers as a tenant, but the real safety net is UptimeRobot. If watchtower dies, UptimeRobot stops getting 200s and pages
