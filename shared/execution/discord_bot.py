"""
discord_bot.py - Discord bot that lets the agent send messages, create channels, and more.

Runs as a persistent bot connected to your Discord server.
The agent can call functions in this file directly, or run it as a subprocess.

Usage:
    python execution/discord_bot.py                    # start the bot
    python execution/discord_bot.py --send #channel "message"
    python execution/discord_bot.py --create-channel "channel-name"
    python execution/discord_bot.py --create-category "category-name"
    python execution/discord_bot.py --list-channels

Environment variables required:
    DISCORD_BOT_TOKEN, DISCORD_GUILD_ID
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

# Load .env
WORKSPACE_ROOT = Path(__file__).parent.parent.parent
env_path = WORKSPACE_ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
GUILD_ID = os.environ.get("DISCORD_GUILD_ID", "")
BASE_URL = "https://discord.com/api/v10"


def headers():
    return {
        "Authorization": f"Bot {TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "DiscordBot (agent, 1.0)",
    }


def request(method: str, path: str, data: dict = None) -> dict:
    url = f"{BASE_URL}{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers(), method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read()) if resp.length != 0 else {}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        print(f"Discord API error {e.code}: {error_body}")
        sys.exit(1)


def get_guild_channels() -> list:
    return request("GET", f"/guilds/{GUILD_ID}/channels")


def create_webhook(channel_id: str, name: str = "agent") -> str:
    """Create a webhook for a channel and return its URL."""
    result = request("POST", f"/channels/{channel_id}/webhooks", {"name": name})
    return f"https://discord.com/api/webhooks/{result['id']}/{result['token']}"


def find_channel(name_or_id: str) -> dict | None:
    """Find a channel by name (with or without #) or ID."""
    name_or_id = name_or_id.lstrip("#")
    channels = get_guild_channels()
    for ch in channels:
        if ch["id"] == name_or_id or ch.get("name", "").lower() == name_or_id.lower():
            return ch
    return None


def send_message(channel_name_or_id: str, message: str, embed: dict = None) -> dict:
    """Send a message to a channel by name or ID."""
    channel = find_channel(channel_name_or_id)
    if not channel:
        print(f"Channel not found: {channel_name_or_id}")
        sys.exit(1)
    data = {"content": message}
    if embed:
        data["embeds"] = [embed]
    result = request("POST", f"/channels/{channel['id']}/messages", data)
    print(f"Message sent to #{channel['name']}")
    return result


def create_channel(name: str, category_name: str = None, channel_type: int = 0) -> dict:
    """
    Create a text channel (type 0) or other channel type.
    Optionally place it under a category.
    """
    name = name.lower().replace(" ", "-")
    data = {"name": name, "type": channel_type}

    if category_name:
        channels = get_guild_channels()
        category = next(
            (c for c in channels if c["type"] == 4 and c["name"].lower() == category_name.lower()),
            None
        )
        if category:
            data["parent_id"] = category["id"]
        else:
            print(f"Category '{category_name}' not found - creating channel without category")

    result = request("POST", f"/guilds/{GUILD_ID}/channels", data)
    print(f"Created channel: #{result['name']} (ID: {result['id']})")
    return result


def create_category(name: str) -> dict:
    """Create a channel category."""
    result = request("POST", f"/guilds/{GUILD_ID}/channels", {"name": name, "type": 4})
    print(f"Created category: {result['name']} (ID: {result['id']})")
    return result


def list_channels() -> list:
    """List all channels and categories in the server."""
    channels = get_guild_channels()
    categories = {c["id"]: c["name"] for c in channels if c["type"] == 4}

    print(f"\nChannels in server (Guild ID: {GUILD_ID}):\n")
    # Print categories and their channels
    printed = set()
    for cat_id, cat_name in sorted(categories.items(), key=lambda x: x[1]):
        print(f"  [{cat_name}]")
        for ch in sorted(channels, key=lambda c: c.get("position", 0)):
            if ch.get("parent_id") == cat_id and ch["type"] == 0:
                print(f"    #{ch['name']} ({ch['id']})")
                printed.add(ch["id"])

    # Uncategorized
    uncategorized = [c for c in channels if c["type"] == 0 and c["id"] not in printed]
    if uncategorized:
        print("  [No Category]")
        for ch in uncategorized:
            print(f"    #{ch['name']} ({ch['id']})")

    return channels


def delete_channel(name_or_id: str) -> None:
    channel = find_channel(name_or_id)
    if not channel:
        print(f"Channel not found: {name_or_id}")
        sys.exit(1)
    request("DELETE", f"/channels/{channel['id']}")
    print(f"Deleted channel: #{channel['name']}")


def main():
    parser = argparse.ArgumentParser(description="Discord bot CLI")
    subparsers = parser.add_subparsers(dest="command")

    # send
    p_send = subparsers.add_parser("send", help="Send a message to a channel")
    p_send.add_argument("channel", help="Channel name or ID (with or without #)")
    p_send.add_argument("message", help="Message to send")

    # create-channel
    p_cc = subparsers.add_parser("create-channel", help="Create a text channel")
    p_cc.add_argument("name", help="Channel name")
    p_cc.add_argument("--category", help="Category to place it under", default=None)

    # create-category
    p_cat = subparsers.add_parser("create-category", help="Create a category")
    p_cat.add_argument("name", help="Category name")

    # list
    subparsers.add_parser("list", help="List all channels")

    # delete
    p_del = subparsers.add_parser("delete-channel", help="Delete a channel")
    p_del.add_argument("channel", help="Channel name or ID")

    args = parser.parse_args()

    if not TOKEN:
        print("ERROR: DISCORD_BOT_TOKEN not set in .env")
        sys.exit(1)
    if not GUILD_ID:
        print("ERROR: DISCORD_GUILD_ID not set in .env")
        sys.exit(1)

    if args.command == "send":
        send_message(args.channel, args.message)
    elif args.command == "create-channel":
        create_channel(args.name, args.category)
    elif args.command == "create-category":
        create_category(args.name)
    elif args.command == "list":
        list_channels()
    elif args.command == "delete-channel":
        delete_channel(args.channel)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
