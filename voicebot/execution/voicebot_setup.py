"""
voicebot_setup.py - Install and verify all voice bot dependencies

Usage:
    python voicebot/execution/voicebot_setup.py
"""

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent

PACKAGES = [
    "twilio",
    "fastapi",
    "uvicorn",
    "anthropic",
    "python-dotenv",
    "ngrok",
]

REQUIRED_ENV_KEYS = [
    "ANTHROPIC_API_KEY",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_PHONE_NUMBER",
]


def install():
    print("Installing voice bot dependencies...")
    for pkg in PACKAGES:
        print(f"  Installing {pkg}...")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", pkg, "-q"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"  ERROR: {result.stderr[-200:]}")
        else:
            print(f"  {pkg} OK")


def verify_imports():
    print("\nVerifying imports...")
    modules = [
        ("twilio", "twilio"),
        ("fastapi", "fastapi"),
        ("uvicorn", "uvicorn"),
        ("anthropic", "anthropic"),
        ("dotenv", "python-dotenv"),
    ]
    all_ok = True
    for module, pkg in modules:
        try:
            __import__(module)
            print(f"  {pkg} - OK")
        except ImportError as e:
            print(f"  {pkg} - FAILED: {e}")
            all_ok = False
    return all_ok


def check_env():
    print("\nChecking .env keys...")
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        print("  .env not found at", env_path)
        return False

    env = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()

    all_set = True
    for key in REQUIRED_ENV_KEYS:
        val = env.get(key, "")
        if val and not val.startswith("YOUR_"):
            print(f"  {key} - OK ({val[:8]}...)")
        else:
            print(f"  {key} - NOT SET")
            all_set = False

    if not all_set:
        print("\n  Add missing keys to your .env file:")
        print("  TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        print("  TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        print("  TWILIO_PHONE_NUMBER=+1xxxxxxxxxx")
        print("  ANTHROPIC_API_KEY=sk-ant-xxxx")
        print("\n  Get Twilio keys at: https://console.twilio.com")
        print("  Get Anthropic key at: https://console.anthropic.com/settings/keys")

    return all_set


def create_dirs():
    dirs = [
        PROJECT_ROOT / ".tmp" / "voicebot" / "calls",
        PROJECT_ROOT / ".tmp" / "voicebot" / "configs",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    print(f"\nCreated temp directories in .tmp/voicebot/")


if __name__ == "__main__":
    install()
    imports_ok = verify_imports()
    env_ok = check_env()
    create_dirs()

    print("\n" + "="*40)
    if imports_ok and env_ok:
        print("Setup complete. Ready to build.")
    elif imports_ok:
        print("Packages installed. Add missing .env keys then run again.")
    else:
        print("Setup had errors - check above.")
