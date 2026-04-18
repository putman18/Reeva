"""
heartbeat.py - Tenant registration and heartbeat tracking.

Tenants (long-running processes) register a name + expected_interval + silent-death rule.
The watchtower stores last-seen timestamps in a SQLite DB and exposes them via health.py.

Two failure modes this catches (per the chatroom postmortem):
1. Process death: tenant stops sending heartbeats -> silent_death_alert
2. Operational death: tenant alive but operational metric violates rule -> operational_failure_alert
"""

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from . import notifier

PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH = PROJECT_ROOT / ".tmp" / "watchtower.sqlite"
DB_PATH.parent.mkdir(exist_ok=True)


def _init_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS tenants (
                name TEXT PRIMARY KEY,
                expected_interval_secs INTEGER NOT NULL,
                silent_death_rule TEXT NOT NULL,
                registered_at REAL NOT NULL,
                last_seen REAL,
                last_status TEXT,
                last_metrics TEXT,
                last_alert_sent_at REAL,
                operational_failure_at REAL
            )
        """)


@contextmanager
def _conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def register(name: str, expected_interval_secs: int, silent_death_rule: str) -> None:
    """
    Register a tenant. Idempotent — re-registering updates expected_interval and rule.

    Sends a boot_ping immediately (the 60s boot ping requirement from the contract).
    """
    _init_db()
    now = time.time()
    with _conn() as c:
        c.execute("""
            INSERT INTO tenants (name, expected_interval_secs, silent_death_rule, registered_at, last_seen)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                expected_interval_secs = excluded.expected_interval_secs,
                silent_death_rule = excluded.silent_death_rule,
                registered_at = excluded.registered_at,
                last_seen = excluded.last_seen
        """, (name, expected_interval_secs, silent_death_rule, now, now))

    # Boot ping per Deploy Contract clause 1
    notifier.boot_ping(name)


def beat(name: str, status: str = "ok", metrics: Optional[dict] = None) -> None:
    """
    Record a heartbeat from a tenant.

    metrics: optional dict of operational counters used to evaluate the silent-death rule
             (e.g. {"trades_today": 3, "expected_daily_trades": 12})
    """
    _init_db()
    now = time.time()
    metrics_json = json.dumps(metrics) if metrics else None
    with _conn() as c:
        c.execute("""
            UPDATE tenants
            SET last_seen = ?, last_status = ?, last_metrics = ?
            WHERE name = ?
        """, (now, status, metrics_json, name))


def list_tenants() -> list[dict]:
    """Return all registered tenants with their current state."""
    _init_db()
    with _conn() as c:
        rows = c.execute("SELECT * FROM tenants").fetchall()
        return [dict(r) for r in rows]


def evaluate_silent_deaths(grace_multiplier: float = 2.0) -> list[dict]:
    """
    Check every tenant for silent death. Fires alerts for any that have missed their window.

    A tenant is in silent death if last_seen is older than expected_interval * grace_multiplier.
    grace_multiplier=2.0 means we tolerate one missed beat before alerting.

    To avoid alert spam, we only fire once per silent-death incident — re-fires only after
    the tenant beats again (clearing operational_failure_at) and dies again.

    Returns list of tenants that triggered alerts.
    """
    _init_db()
    now = time.time()
    triggered = []

    with _conn() as c:
        rows = c.execute("SELECT * FROM tenants").fetchall()
        for row in rows:
            t = dict(row)
            last_seen = t["last_seen"] or t["registered_at"]
            silence_secs = now - last_seen
            allowed_silence = t["expected_interval_secs"] * grace_multiplier

            if silence_secs > allowed_silence:
                # Already alerted for this incident? Skip.
                if t["last_alert_sent_at"] and t["last_alert_sent_at"] > last_seen:
                    continue

                notifier.silent_death_alert(
                    service_name=t["name"],
                    rule=f"expected heartbeat every {t['expected_interval_secs']}s, last seen {silence_secs:.0f}s ago",
                    last_seen_secs=silence_secs,
                )
                c.execute("UPDATE tenants SET last_alert_sent_at = ? WHERE name = ?", (now, t["name"]))
                triggered.append(t)

    return triggered


def evaluate_operational_failures(rule_evaluator) -> list[dict]:
    """
    Check every tenant for operational failure (process alive but doing wrong thing).

    rule_evaluator: a callable (tenant_dict, metrics_dict) -> (violated: bool, reason: str)
                    The caller provides the evaluator because rules are tenant-specific
                    (e.g. "during market hours" requires NYSE calendar logic).

    Returns list of tenants whose rules were violated.
    """
    _init_db()
    now = time.time()
    triggered = []

    with _conn() as c:
        rows = c.execute("SELECT * FROM tenants WHERE last_metrics IS NOT NULL").fetchall()
        for row in rows:
            t = dict(row)
            metrics = json.loads(t["last_metrics"])
            violated, reason = rule_evaluator(t, metrics)
            if violated:
                # Don't re-fire if we already alerted for this state
                if t["operational_failure_at"]:
                    continue

                notifier.operational_failure_alert(
                    service_name=t["name"],
                    rule=t["silent_death_rule"] + " | " + reason,
                    observed=metrics,
                )
                c.execute("UPDATE tenants SET operational_failure_at = ? WHERE name = ?", (now, t["name"]))
                triggered.append(t)
            else:
                # Clear stale failure flag if metrics now pass
                if t["operational_failure_at"]:
                    c.execute("UPDATE tenants SET operational_failure_at = NULL WHERE name = ?", (t["name"],))

    return triggered


def watchtower_loop(check_every_secs: int = 60):
    """
    The watchtower itself. Run as its own process.

    Self-registers as 'watchtower' so its own death is visible — but per the contract,
    UptimeRobot is the external watcher that catches watchtower silence (no infinite regress).
    """
    register(
        "watchtower",
        expected_interval_secs=check_every_secs,
        silent_death_rule="watchtower itself: should beat every check_every_secs",
    )
    print(f"[watchtower] Loop started, checking every {check_every_secs}s")

    while True:
        beat("watchtower", status="ok")
        triggered = evaluate_silent_deaths()
        if triggered:
            print(f"[watchtower] Silent death alerts fired: {[t['name'] for t in triggered]}")
        time.sleep(check_every_secs)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "loop":
        check_every = int(sys.argv[2]) if len(sys.argv) > 2 else 60
        watchtower_loop(check_every)
    elif len(sys.argv) > 1 and sys.argv[1] == "list":
        for t in list_tenants():
            last_seen_age = time.time() - (t["last_seen"] or t["registered_at"])
            print(f"  {t['name']}: last seen {last_seen_age:.0f}s ago, expected every {t['expected_interval_secs']}s")
    else:
        print("Usage: python heartbeat.py loop [check_every_secs] | list")
