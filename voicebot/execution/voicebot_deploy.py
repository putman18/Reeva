"""
voicebot_deploy.py - Deploy voicebot to Hostinger VPS

What this does:
    1. Copies voicebot files to the VPS
    2. Copies .env file
    3. Installs Python dependencies
    4. Sets up systemd service so server runs permanently
    5. Prints the public URL to paste into Twilio

Run from your local terminal:
    python voicebot/execution/voicebot_deploy.py

Requirements:
    - SSH key access to the VPS already set up
    - rsync installed (comes with Git Bash / WSL on Windows)
"""

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
VOICEBOT_DIR = Path(__file__).parent.parent

VPS_HOST = "root@187.124.250.181"
VPS_DIR = "/opt/voicebot"
PORT = 8001

SYSTEMD_SERVICE = f"""[Unit]
Description=Voicebot AI Receptionist
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory={VPS_DIR}/execution
ExecStart={VPS_DIR}/venv/bin/python {VPS_DIR}/execution/voicebot_server.py
Restart=always
RestartSec=5
Environment=PORT={PORT}

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


def deploy():
    print("=" * 50)
    print("Voicebot Deploy to Hostinger VPS")
    print("=" * 50)

    # Step 1: Create directory on VPS
    print("\n[1/5] Creating VPS directory...")
    ssh(f"mkdir -p {VPS_DIR}/execution")

    # Step 2: Copy voicebot files
    print("\n[2/5] Copying voicebot files...")
    run(f'scp -r -o StrictHostKeyChecking=no "{VOICEBOT_DIR}/execution" {VPS_HOST}:{VPS_DIR}/')
    run(f'scp -o StrictHostKeyChecking=no "{VOICEBOT_DIR}/credentials.json" {VPS_HOST}:{VPS_DIR}/', check=False)

    # Step 3: Copy .env file
    print("\n[3/5] Copying .env file...")
    run(f'scp "{PROJECT_ROOT}/.env" {VPS_HOST}:{VPS_DIR}/../.env')

    # Step 4: Install dependencies on VPS
    print("\n[4/5] Installing dependencies on VPS...")
    ssh("apt-get install -y python3-pip python3-venv python3-full > /dev/null 2>&1 || true")
    ssh(f"python3 -m venv {VPS_DIR}/venv")
    ssh(f"{VPS_DIR}/venv/bin/pip install fastapi uvicorn anthropic twilio google-api-python-client google-auth-httplib2 google-auth-oauthlib python-dotenv python-multipart -q")

    # Step 5: Copy Google token if it exists
    token_file = VOICEBOT_DIR / "token.json"
    if token_file.exists():
        print("\n  Copying Google Calendar token...")
        run(f'scp "{token_file}" {VPS_HOST}:{VPS_DIR}/token.json')

    # Step 6: Set up systemd service
    print("\n[5/5] Setting up systemd service...")
    service_content = SYSTEMD_SERVICE.replace('"', '\\"')

    ssh(f'cat > /etc/systemd/system/voicebot.service << \'EOF\'\n{SYSTEMD_SERVICE}\nEOF\'')
    ssh("systemctl daemon-reload")
    ssh("systemctl enable voicebot")
    ssh("systemctl restart voicebot")

    # Verify it's running
    import time
    time.sleep(3)
    status = ssh("systemctl is-active voicebot", check=False)

    print("\n" + "=" * 50)
    if status == "active":
        print("DEPLOYED SUCCESSFULLY")
        print(f"\nPublic URL: http://187.124.250.181:{PORT}")
        print("\nNow configure Twilio:")
        print(f"  1. Go to console.twilio.com")
        print(f"  2. Phone Numbers > Manage > Active Numbers > click your number")
        print(f"  3. Voice Configuration > A call comes in > Webhook:")
        print(f"     http://187.124.250.181:{PORT}/call/start")
        print(f"  4. Set HTTP method to POST")
        print(f"  5. Save")
        print(f"\nCall your Twilio number to test the full flow.")
    else:
        print("Deploy finished but service may not be running.")
        print("Check with: ssh root@187.124.250.181 'journalctl -u voicebot -n 50'")


if __name__ == "__main__":
    deploy()
