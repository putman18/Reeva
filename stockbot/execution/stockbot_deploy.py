"""
stockbot_deploy.py - Deploy stockbot + dashboard to Hostinger VPS.

Two systemd services:
  - stockbot:           main trading bot loop
  - stockbot-dashboard: FastAPI dashboard on port 8766

Run:
    python stockbot/execution/stockbot_deploy.py
"""

import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
STOCKBOT_LOCAL = PROJECT_ROOT / "stockbot"

VPS_HOST = "root@187.124.250.181"
VPS_DIR = "/opt/stockbot"
DASHBOARD_PORT = 8766

BOT_SERVICE = f"""[Unit]
Description=Stockbot VWAP Trading Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory={VPS_DIR}
ExecStart={VPS_DIR}/venv/bin/python -m stockbot.execution.stockbot
Restart=always
RestartSec=10
Environment=PYTHONIOENCODING=utf-8

[Install]
WantedBy=multi-user.target
"""

DASHBOARD_SERVICE = f"""[Unit]
Description=Stockbot Dashboard
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory={VPS_DIR}
ExecStart={VPS_DIR}/venv/bin/python -m stockbot.execution.stockbot_dashboard
Restart=always
RestartSec=10
Environment=PYTHONIOENCODING=utf-8

[Install]
WantedBy=multi-user.target
"""


def run(cmd: str, check: bool = True) -> str:
    print(f"  $ {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout:
        print(f"    {result.stdout.strip()}")
    if result.returncode != 0 and check:
        print(f"    ERROR: {result.stderr.strip()}")
        sys.exit(1)
    return result.stdout.strip()


def ssh(cmd: str, check: bool = True) -> str:
    return run(f'ssh -o StrictHostKeyChecking=no {VPS_HOST} "{cmd}"', check=check)


def write_service(name: str, content: str):
    tmp = PROJECT_ROOT / ".tmp" / f"{name}.service"
    tmp.parent.mkdir(exist_ok=True)
    tmp.write_text(content)
    run(f'scp -o StrictHostKeyChecking=no "{tmp}" {VPS_HOST}:/etc/systemd/system/{name}.service')


def deploy():
    print("=" * 50)
    print("Stockbot Deploy to Hostinger VPS")
    print("=" * 50)

    print("\n[1/8] Creating VPS directory structure...")
    ssh(f"mkdir -p {VPS_DIR}/stockbot/execution {VPS_DIR}/stockbot/directives {VPS_DIR}/shared/watchtower {VPS_DIR}/.tmp")

    print("\n[2/8] Copying stockbot module...")
    run(f'scp -r -o StrictHostKeyChecking=no "{STOCKBOT_LOCAL}/." {VPS_HOST}:{VPS_DIR}/stockbot/')

    print("\n[3/8] Copying shared/watchtower module...")
    run(f'scp -r -o StrictHostKeyChecking=no "{PROJECT_ROOT / "shared" / "watchtower"}/." {VPS_HOST}:{VPS_DIR}/shared/watchtower/')

    print("\n[4/8] Copying .env...")
    run(f'scp -o StrictHostKeyChecking=no "{PROJECT_ROOT / ".env"}" {VPS_HOST}:{VPS_DIR}/.env')

    print("\n[5/8] Setting up venv and dependencies...")
    ssh("apt-get install -y python3-venv python3-pip > /dev/null 2>&1 || true")
    ssh(f"python3 -m venv {VPS_DIR}/venv")
    ssh(f"{VPS_DIR}/venv/bin/pip install --quiet alpaca-py python-dotenv anthropic fastapi uvicorn pytz")

    print("\n[6/8] Opening firewall for dashboard port...")
    ssh(f"ufw allow {DASHBOARD_PORT}/tcp > /dev/null 2>&1 || true")
    ssh(f"iptables -I INPUT -p tcp --dport {DASHBOARD_PORT} -j ACCEPT > /dev/null 2>&1 || true")

    print("\n[7/8] Installing systemd units...")
    write_service("stockbot", BOT_SERVICE)
    write_service("stockbot-dashboard", DASHBOARD_SERVICE)

    print("\n[8/8] Enabling and starting services...")
    ssh("systemctl daemon-reload")
    for svc in ["stockbot", "stockbot-dashboard"]:
        ssh(f"systemctl enable {svc}")
        ssh(f"systemctl restart {svc}")

    time.sleep(5)
    print("\n" + "=" * 50)
    print("Status:")
    for svc in ["stockbot", "stockbot-dashboard"]:
        status = ssh(f"systemctl is-active {svc}", check=False)
        print(f"  {svc}: {status}")

    print("\nRecent bot logs:")
    ssh("journalctl -u stockbot -n 10 --no-pager", check=False)

    print("\n" + "=" * 50)
    print("DEPLOYED")
    print(f"\nDashboard:   http://187.124.250.181:{DASHBOARD_PORT}")
    print(f"Health:      http://187.124.250.181:8765/health")
    print(f"Tenants:     http://187.124.250.181:8765/tenants")
    print(f"\nLogs:  ssh {VPS_HOST} 'journalctl -u stockbot -f'")
    print(f"Stop:  ssh {VPS_HOST} 'systemctl stop stockbot'")


if __name__ == "__main__":
    deploy()
