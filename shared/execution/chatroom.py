"""
chatroom.py - Multi-personality Claude chatroom for stress-testing ideas.

Spawns multiple Claude personalities that respond to your topic in sequence.
Each personality sees the full conversation, including what the others said.

Usage:
    python shared/execution/chatroom.py
    python shared/execution/chatroom.py --personalities user_advocate,contrarian
    python shared/execution/chatroom.py --topic "Should we ship the voicebot to 10 clients next month?"

Personalities:
    user_advocate    - represents the end user, plain-language reality check
    edgecase_hunter  - finds what breaks, weird inputs, the 1% scenarios
    contrarian       - argues the opposite, challenges consensus
    pragmatist       - reality check on time/cost/shipping, cuts scope
    visionary        - long-term thinking, where does this go in 2 years
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

import anthropic

MODEL = "claude-sonnet-4-6"

PERSONALITIES = {
    "user_advocate": {
        "name": "User Advocate",
        "color": "\033[96m",  # cyan
        "system": (
            "You are the User Advocate. You represent the real end user — "
            "not a technical user, not a stakeholder, just the human who has to use this thing. "
            "Ask: would my mom understand this? Would a busy person stick with it? "
            "Where will real users get confused, frustrated, or quit? "
            "Be specific about user pain. Speak in plain language. "
            "Keep responses under 4 sentences."
        ),
    },
    "edgecase_hunter": {
        "name": "Edgecase Hunter",
        "color": "\033[93m",  # yellow
        "system": (
            "You are the Edgecase Hunter. Your only job is to find what breaks. "
            "Weird inputs, race conditions, network failures, malicious users, "
            "the 1% scenarios everyone forgets. Always ask 'what happens when X fails?' "
            "Be specific — name the exact scenario, not 'errors should be handled.' "
            "Keep responses under 4 sentences."
        ),
    },
    "contrarian": {
        "name": "Contrarian",
        "color": "\033[91m",  # red
        "system": (
            "You are the Contrarian. Your job is to argue against whatever was just said. "
            "If everyone agrees, find the hidden assumption and attack it. "
            "If the plan is to ship fast, argue for going slow. If the plan is careful, argue for shipping now. "
            "You are not contrarian for sport — you are stress-testing the consensus. "
            "Always include the strongest counterargument. Keep responses under 4 sentences."
        ),
    },
    "pragmatist": {
        "name": "Pragmatist",
        "color": "\033[92m",  # green
        "system": (
            "You are the Pragmatist. You only care about what ships and what it costs. "
            "Cut scope ruthlessly. Ask: what is the smallest version that delivers value? "
            "What can we drop? What's the deadline? What's the actual budget? "
            "Ignore long-term vision and edge cases — focus on what can be done this week. "
            "Keep responses under 4 sentences."
        ),
    },
    "visionary": {
        "name": "Visionary",
        "color": "\033[95m",  # magenta
        "system": (
            "You are the Visionary. You think about where this goes in 2 years, not next week. "
            "Connect the current decision to bigger trends, downstream consequences, "
            "and second-order effects. Ask: what does success look like at scale? "
            "What are we accidentally building toward? Be bold but specific. "
            "Keep responses under 4 sentences."
        ),
    },
}

RESET = "\033[0m"
BOLD = "\033[1m"


def get_personality_response(client, personality_key, topic, conversation_log):
    """Get one personality's response to the current state of the conversation."""
    p = PERSONALITIES[personality_key]

    history_text = ""
    for entry in conversation_log:
        history_text += f"\n[{entry['speaker']}]: {entry['message']}\n"

    user_message = (
        f"TOPIC: {topic}\n\n"
        f"CONVERSATION SO FAR:{history_text}\n\n"
        f"Respond as {p['name']}. Stay in character. Address the topic and react to what others have said."
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=400,
        system=p["system"],
        messages=[{"role": "user", "content": user_message}],
    )

    return response.content[0].text


def print_speaker(personality_key, message):
    p = PERSONALITIES[personality_key]
    safe = message.encode("cp1252", errors="replace").decode("cp1252")
    print(f"\n{p['color']}{BOLD}{p['name']}:{RESET} {safe}\n")


def save_transcript(topic, conversation_log):
    out_dir = PROJECT_ROOT / ".tmp"
    out_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"chatroom_{timestamp}.txt"

    with open(out_file, "w", encoding="utf-8") as f:
        f.write(f"TOPIC: {topic}\n")
        f.write(f"DATE: {datetime.now().isoformat()}\n")
        f.write("=" * 60 + "\n\n")
        for entry in conversation_log:
            f.write(f"[{entry['speaker']}]\n{entry['message']}\n\n")

    return out_file


def main():
    parser = argparse.ArgumentParser(description="Multi-personality Claude chatroom")
    parser.add_argument(
        "--personalities",
        default="visionary,pragmatist,contrarian,edgecase_hunter,user_advocate",
        help="Comma-separated list of personalities (default: all 5)",
    )
    parser.add_argument("--topic", help="Initial topic (otherwise prompted)")
    parser.add_argument("--rounds", type=int, default=1, help="How many rounds per turn (default: 1)")
    args = parser.parse_args()

    selected = [p.strip() for p in args.personalities.split(",")]
    for p in selected:
        if p not in PERSONALITIES:
            print(f"Unknown personality: {p}")
            print(f"Available: {', '.join(PERSONALITIES.keys())}")
            sys.exit(1)

    print(f"\n{BOLD}=== Claude Chatroom ==={RESET}")
    print(f"Personalities: {', '.join(PERSONALITIES[p]['name'] for p in selected)}")
    print(f"Model: {MODEL}")
    print(f"Type 'quit' to exit, 'save' to save transcript, or new input to continue.\n")

    topic = args.topic or input(f"{BOLD}Topic:{RESET} ").strip()
    if not topic:
        print("No topic given.")
        sys.exit(1)

    client = anthropic.Anthropic()
    conversation_log = []

    user_input = topic

    while True:
        conversation_log.append({"speaker": "USER", "message": user_input})

        for _ in range(args.rounds):
            for personality_key in selected:
                response = get_personality_response(client, personality_key, topic, conversation_log)
                print_speaker(personality_key, response)
                conversation_log.append(
                    {"speaker": PERSONALITIES[personality_key]["name"], "message": response}
                )

        # If topic was passed via --topic (non-interactive), auto-save and exit
        if args.topic:
            out = save_transcript(topic, conversation_log)
            print(f"\nTranscript saved to {out}")
            break

        next_input = input(f"{BOLD}You:{RESET} ").strip()
        if not next_input:
            continue
        if next_input.lower() in ("quit", "exit", "q"):
            out = save_transcript(topic, conversation_log)
            print(f"\nTranscript saved to {out}")
            break
        if next_input.lower() == "save":
            out = save_transcript(topic, conversation_log)
            print(f"Transcript saved to {out}\n")
            continue
        user_input = next_input


if __name__ == "__main__":
    main()
