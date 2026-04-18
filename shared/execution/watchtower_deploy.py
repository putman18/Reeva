"""
watchtower_deploy.py - Deploy watchtower to Hostinger VPS.

Models on voicebot_deploy.py. Deploys two systemd services:
  - watchtower-loop:    runs heartbeat.watchtower_loop() forever, checks tenants every 60s
  - watchtower-health:  runs health.serve() on port 8765 for UptimeRobot to ping

Run from local terminal:
    python shared/execution/watchtower_deploy.py
"""

import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
WATCHTOWER_LOCAL = PROJECT_ROOT / "shared" / "watchtower"

VPS_HOST = "root@187.124.250.181"
VPS_DIR = "/opt/watchtower"
HEALTH_PORT = 8765

LOOP_SERVICE = f"""[Unit]
Description=Watchtower Heartbeat Loop
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory={VPS_DIR}
ExecStart={VPS_DIR}/venv/bin/python -m shared.watchtower.heartbeat loop 60
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"""

HEALTH_SERVICE = f"""[Unit]
Description=Watchtower Health Endpoint
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory={VPS_DIR}
ExecStart={VPS_DIR}/venv/bin/python -m shared.watchtower.health {HEALTH_PORT}
Restart=always
RestartSec=5

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


def write_systemd_unit(name: str, content: str):
    """Write a systemd unit file via heredoc over SSH."""
    # Escape any double quotes in the content for the shell heredoc
    escaped = content.replace('$', '\\$')
    heredoc = f"cat > /etc/systemd/system/{name}.service << 'EOF'\n{escaped}\nEOF"
    # Write to a temp file locally, then scp + bash it (simpler than escaping)
    tmp = PROJECT_ROOT / ".tmp" / f"{name}.service"
    tmp.parent.mkdir(exist_ok=True)
    tmp.write_text(content)
    run(f'scp -o StrictHostKeyChecking=no "{tmp}" {VPS_HOST}:/etc/systemd/system/{name}.service')


def deploy():
    print("=" * 50)
    print("Watchtower Deploy to Hostinger VPS")
    print("=" * 50)

    # Step 1: Create directory structure on VPS
    print("\n[1/7] Creating VPS directory structure...")
    ssh(f"mkdir -p {VPS_DIR}/shared/watchtower {VPS_DIR}/.tmp")

    # Step 2: Copy watchtower module
    print("\n[2/7] Copying watchtower module...")
    run(f'scp -r -o StrictHostKeyChecking=no "{WATCHTOWER_LOCAL}/." {VPS_HOST}:{VPS_DIR}/shared/watchtower/')

    # Step 3: Copy .env
    print("\n[3/7] Copying .env...")
    run(f'scp -o StrictHostKeyChecking=no "{PROJECT_ROOT / ".env"}" {VPS_HOST}:{VPS_DIR}/.env')

    # Step 4: Set up venv (no third-party deps needed — stdlib only)
    print("\n[4/7] Setting up venv (stdlib only, no pip installs needed)...")
    ssh("apt-get install -y python3-venv > /dev/null 2>&1 || true")
    ssh(f"python3 -m venv {VPS_DIR}/venv")

    # Step 5: Install systemd units
    print("\n[5/7] Installing systemd units...")
    write_systemd_unit("watchtower-loop", LOOP_SERVICE)
    write_systemd_unit("watchtower-health", HEALTH_SERVICE)

    # Step 6: Open firewall for health port
    print(f"\n[6/7] Opening firewall for port {HEALTH_PORT}...")
    # Hostinger uses ufw or iptables — try both gracefully
    ssh(f"ufw allow {HEALTH_PORT}/tcp > /dev/null 2>&1 || true")
    ssh(f"iptables -I INPUT -p tcp --dport {HEALTH_PORT} -j ACCEPT > /dev/null 2>&1 || true")

    # Step 7: Enable and start services
    print("\n[7/7] Starting services...")
    ssh("systemctl daemon-reload")
    for svc in ["watchtower-loop", "watchtower-health"]:
        ssh(f"systemctl enable {svc}")
        ssh(f"systemctl restart {svc}")

    # Verify
    time.sleep(4)
    print("\n" + "=" * 50)
    print("Status check:")
    for svc in ["watchtower-loop", "watchtower-health"]:
        status = ssh(f"systemctl is-active {svc}", check=False)
        print(f"  {svc}: {status}")

    # Test the health endpoint from the server itself
    print("\nLocal health probe from server:")
    ssh(f"curl -s http://localhost:{HEALTH_PORT}/health || echo 'health endpoint not responding'", check=False)

    print("\n" + "=" * 50)
    print("DEPLOYED")
    print(f"\nHealth endpoint: http://187.124.250.181:{HEALTH_PORT}/health")
    print(f"Tenant list:     http://187.124.250.181:{HEALTH_PORT}/tenants")
    print(f"\nBoot ping should now be in #trade-alerts on Discord (from the SERVER, not laptop).")
    print(f"\nNext: set up UptimeRobot to ping http://187.124.250.181:{HEALTH_PORT}/health every 5 min.")
    print(f"\nTo check logs:")
    print(f"  ssh {VPS_HOST} 'journalctl -u watchtower-loop -n 30'")
    print(f"  ssh {VPS_HOST} 'journalctl -u watchtower-health -n 30'")


if __name__ == "__main__":
    deploy()
