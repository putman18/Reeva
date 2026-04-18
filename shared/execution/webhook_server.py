"""
webhook_server.py - Local webhook server that runs on your machine.

Each POST /<slug> maps to a directive via webhooks.json.
The agent reads the directive and processes the payload via Claude API.

Start:
    python execution/webhook_server.py
    python execution/webhook_server.py --port 8888  # custom port

Test:
    curl -X POST http://localhost:8000/<slug> -H "Content-Type: application/json" -d '{...}'
"""

import argparse
import json
import os
import sys
from pathlib import Path

import anthropic
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

load_dotenv()

PROJECT_DIR = Path(__file__).parent.parent.parent
app = FastAPI(title="Agent Webhook Server")


def load_webhooks() -> dict:
    webhooks_path = PROJECT_DIR / "execution" / "webhooks.json"
    if not webhooks_path.exists():
        return {}
    with open(webhooks_path) as f:
        data = json.load(f)
    return {w["slug"]: w for w in data.get("webhooks", [])}


def load_directive(directive_file: str) -> str:
    path = PROJECT_DIR / "directives" / directive_file
    if not path.exists():
        raise FileNotFoundError(f"Directive not found: {directive_file}")
    return path.read_text()


@app.post("/{slug}")
async def webhook(slug: str, request: Request) -> JSONResponse:
    webhooks = load_webhooks()

    if slug not in webhooks:
        raise HTTPException(status_code=404, detail=f"Unknown webhook slug: {slug}")

    config = webhooks[slug]
    directive_file = config.get("directive")

    try:
        directive = load_directive(directive_file)
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e))

    payload = await request.json()

    client = anthropic.Anthropic()

    prompt = f"""You are an autonomous agent. Execute the following directive using the provided payload.

DIRECTIVE ({directive_file}):
{directive}

PAYLOAD:
{json.dumps(payload, indent=2)}

Execute the directive. Call the appropriate tools in sequence. Report what you did."""

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    return JSONResponse(
        {
            "status": "ok",
            "slug": slug,
            "result": message.content[0].text if message.content else "",
        }
    )


@app.get("/")
def list_webhooks():
    webhooks = load_webhooks()
    return {"webhooks": list(webhooks.keys())}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Local agent webhook server")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    args = parser.parse_args()

    print(f"Starting webhook server at http://{args.host}:{args.port}")
    print(f"Registered webhooks: {list(load_webhooks().keys()) or '(none)'}")
    uvicorn.run(app, host=args.host, port=args.port)
