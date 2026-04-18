"""
health.py - HTTP endpoint for UptimeRobot to ping.

Returns 200 if all registered tenants are within their expected_interval (with grace).
Returns 503 if any tenant is silent. UptimeRobot pings this every 5 minutes
and alerts the user when it returns non-200 or stops responding.

This is the "watcher of the watcher" — solves the infinite regress problem flagged by
Edgecase Hunter in the chatroom: if watchtower itself dies, UptimeRobot notices.

Run with: python -m shared.watchtower.health [port]
"""

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# Allow running as `python health.py` from inside the directory or as a module
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.watchtower import heartbeat, notifier


GRACE_MULTIPLIER = 2.0


class HealthHandler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        # UptimeRobot sends HEAD — treat it the same as GET /health
        if self.path in ("/health", "/"):
            heartbeat.beat("watchtower-health", status="ok")
            tenants = heartbeat.list_tenants()
            now = time.time()
            stale = [
                t for t in tenants
                if (now - (t["last_seen"] or t["registered_at"])) > t["expected_interval_secs"] * GRACE_MULTIPLIER
            ]
            code = 200 if not stale else 503
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self._respond_health()
        elif self.path == "/tenants":
            self._respond_tenants()
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"not found")

    def _respond_health(self):
        heartbeat.beat("watchtower-health", status="ok")
        tenants = heartbeat.list_tenants()
        now = time.time()
        stale = []
        for t in tenants:
            last_seen = t["last_seen"] or t["registered_at"]
            silence = now - last_seen
            allowed = t["expected_interval_secs"] * GRACE_MULTIPLIER
            if silence > allowed:
                stale.append({
                    "name": t["name"],
                    "silence_secs": int(silence),
                    "allowed_secs": int(allowed),
                })

        body = {
            "status": "ok" if not stale else "degraded",
            "tenant_count": len(tenants),
            "stale_count": len(stale),
            "stale": stale,
            "checked_at": int(now),
        }
        code = 200 if not stale else 503
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode("utf-8"))

    def _respond_tenants(self):
        tenants = heartbeat.list_tenants()
        now = time.time()
        body = []
        for t in tenants:
            last_seen = t["last_seen"] or t["registered_at"]
            body.append({
                "name": t["name"],
                "expected_interval_secs": t["expected_interval_secs"],
                "silent_death_rule": t["silent_death_rule"],
                "last_seen_age_secs": int(now - last_seen),
                "last_status": t["last_status"],
                "last_metrics": json.loads(t["last_metrics"]) if t["last_metrics"] else None,
            })
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body, indent=2).encode("utf-8"))

    def log_message(self, format, *args):
        # Quiet the default access log spam; UptimeRobot pings every 5 min
        pass


def serve(port: int = 8765):
    # Self-register so the health server's own absence is visible
    heartbeat.register(
        "watchtower-health",
        expected_interval_secs=60,
        silent_death_rule="health endpoint should respond to /health",
    )
    notifier.send(
        "trade_alerts",
        embeds=[{
            "title": "WATCHTOWER HEALTH ENDPOINT BOOTED",
            "description": f"Listening on 0.0.0.0:{port}\nUptimeRobot should be pointed at http://<server>:{port}/health",
            "color": 0x00aaff,
        }],
    )
    print(f"[health] Serving on 0.0.0.0:{port}")

    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    def _beat_loop():
        while True:
            heartbeat.beat("watchtower-health", status="ok")
            time.sleep(30)

    t = threading.Thread(target=_beat_loop, daemon=True)
    t.start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[health] Shutting down")
    finally:
        server.server_close()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    serve(port)
