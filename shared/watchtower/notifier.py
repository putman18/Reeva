"""
notifier.py - Discord webhook sender with rate-limit handling.

Used by the watchtower to send boot pings, heartbeats, and silent-death alerts.
Built defensively because Edgecase Hunter (chatroom) noted Discord webhooks rate-limit
at 30/min and a tight retry loop can get the webhook banned.
"""

import json
import os
import time
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path
from threading import Lock
from typing import Optional

PROJECT_ROOT = Path(__file__).parent.parent.parent
ENV_PATH = PROJECT_ROOT / ".env"

# Lazy-load .env once
_env_loaded = False


def _load_env():
    global _env_loaded
    if _env_loaded or not ENV_PATH.exists():
        _env_loaded = True
        return
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())
    _env_loaded = True


# Discord webhook rate limit: 30 requests / 60 seconds per webhook.
# We keep a sliding window of send timestamps and refuse to send if we'd exceed it.
_RATE_LIMIT_WINDOW_SECS = 60
_RATE_LIMIT_MAX_SENDS = 25  # Stay under 30 to be safe
_send_history: dict[str, deque] = {}
_history_lock = Lock()


def _rate_limit_ok(webhook_url: str) -> bool:
    now = time.time()
    with _history_lock:
        history = _send_history.setdefault(webhook_url, deque())
        while history and history[0] < now - _RATE_LIMIT_WINDOW_SECS:
            history.popleft()
        if len(history) >= _RATE_LIMIT_MAX_SENDS:
            return False
        history.append(now)
        return True


def send(
    channel: str,
    content: Optional[str] = None,
    embeds: Optional[list] = None,
    timeout: int = 10,
) -> bool:
    """
    Send a Discord message via webhook.

    channel: short name like "alerts", "trading", "trade_alerts", "backtest".
             Maps to DISCORD_WEBHOOK_<UPPER> env var.
    Returns True on success, False on failure (logged but not raised).
    """
    _load_env()

    env_key = f"DISCORD_WEBHOOK_{channel.upper()}"
    webhook_url = os.environ.get(env_key)
    if not webhook_url:
        print(f"[notifier] No webhook URL for channel '{channel}' (env var {env_key} unset)")
        return False

    if not _rate_limit_ok(webhook_url):
        print(f"[notifier] Rate limit hit for {channel}, dropping message to avoid ban")
        return False

    payload = {}
    if content:
        payload["content"] = content
    if embeds:
        payload["embeds"] = embeds
    if not payload:
        return False

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if 200 <= resp.status < 300:
                return True
            print(f"[notifier] Discord returned {resp.status} for {channel}")
            return False
    except urllib.error.HTTPError as e:
        if e.code == 429:
            # Discord told us to slow down — record an extra send to back us off
            with _history_lock:
                history = _send_history.setdefault(webhook_url, deque())
                for _ in range(5):
                    history.append(time.time())
            print(f"[notifier] Discord 429 on {channel}, backing off")
        else:
            print(f"[notifier] Discord HTTPError {e.code} on {channel}: {e.reason}")
        return False
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"[notifier] Network error sending to {channel}: {e}")
        return False


def boot_ping(service_name: str, channel: str = "trade_alerts") -> bool:
    """Send a boot ping. The 60s window starts when the process starts; this should fire immediately."""
    from datetime import datetime
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return send(
        channel,
        embeds=[{
            "title": f"BOOT: {service_name}",
            "description": f"Process started at {ts}",
            "color": 0x00aaff,
        }],
    )


def silent_death_alert(service_name: str, rule: str, last_seen_secs: float, channel: str = "trade_alerts") -> bool:
    """Send a silent-death alert. Fires when a tenant misses its heartbeat window."""
    return send(
        channel,
        embeds=[{
            "title": f"SILENT DEATH: {service_name}",
            "description": f"No heartbeat in {last_seen_secs:.0f}s. Rule: {rule}",
            "color": 0xff0000,
        }],
    )


def operational_failure_alert(service_name: str, rule: str, observed: dict, channel: str = "trade_alerts") -> bool:
    """Fires when the silent-death rule on operational metrics is violated (process alive, doing wrong thing)."""
    metrics_str = ", ".join(f"{k}={v}" for k, v in observed.items())
    return send(
        channel,
        embeds=[{
            "title": f"OPERATIONAL FAILURE: {service_name}",
            "description": f"Rule violated: {rule}\nObserved: {metrics_str}",
            "color": 0xff6600,
        }],
    )


if __name__ == "__main__":
    # Smoke test
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        ok = boot_ping("watchtower-notifier-smoketest", channel="alerts")
        print(f"Boot ping sent: {ok}")
    else:
        print("Usage: python notifier.py test")
