"""
voicebot_server.py - FastAPI server for Twilio voice webhooks

Endpoints:
    POST /call/start     - Twilio calls this when a call comes in
    POST /call/respond   - Twilio calls this after caller speaks
    POST /call/transfer  - Transfer call to human
    POST /call/complete  - Twilio calls this when call ends

Run:
    python voicebot/execution/voicebot_server.py
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import PlainTextResponse
import uvicorn
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from voicebot_agent import VoicebotSession, CLIENT_CONFIG
from voicebot_crm import get_customer_by_phone

app = FastAPI()

# In-memory session store: call_sid -> VoicebotSession
sessions: dict[str, VoicebotSession] = {}
call_start_times: dict[str, datetime] = {}


def twiml(xml_body: str) -> Response:
    """Return a TwiML XML response."""
    return Response(
        content=f'<?xml version="1.0" encoding="UTF-8"?><Response>{xml_body}</Response>',
        media_type="application/xml"
    )


def say(text: str, voice: str = "Polly.Joanna") -> str:
    """Generate a TwiML <Say> block."""
    safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f'<Say voice="{voice}">{safe}</Say>'


def gather(action: str, timeout: int = 5, speech_timeout: str = "auto") -> tuple[str, str]:
    """Return opening and closing tags for a <Gather> block."""
    open_tag = (
        f'<Gather input="speech" action="{action}" method="POST" '
        f'timeout="{timeout}" speechTimeout="{speech_timeout}">'
    )
    return open_tag, "</Gather>"


# -----------------------------------------------------------------------
# POST /call/start - incoming call
# -----------------------------------------------------------------------

@app.post("/call/start")
async def call_start(
    CallSid: str = Form(...),
    From: str = Form(...),
    To: str = Form(...)
):
    phone = From
    session = VoicebotSession(phone)
    sessions[CallSid] = session
    call_start_times[CallSid] = datetime.now()

    greeting = session.get_opening_greeting()

    open_gather, close_gather = gather("/call/respond")
    body = f"{say(greeting)}{open_gather}{say('Go ahead.')}{close_gather}"
    body += say("I didn't catch that. Please call back and we'll be happy to help.")

    return twiml(body)


# -----------------------------------------------------------------------
# POST /call/respond - process speech input
# -----------------------------------------------------------------------

@app.post("/call/respond")
async def call_respond(
    CallSid: str = Form(...),
    From: str = Form(...),
    SpeechResult: str = Form(default=""),
    Confidence: str = Form(default="0")
):
    session = sessions.get(CallSid)
    if not session:
        session = VoicebotSession(From)
        sessions[CallSid] = session
        call_start_times[CallSid] = datetime.now()

    user_input = SpeechResult.strip()
    if not user_input:
        open_gather, close_gather = gather("/call/respond")
        sorry = say("Sorry, I didn't catch that.")
        go_ahead = say("Go ahead.")
        body = f"{sorry}{open_gather}{go_ahead}{close_gather}"
        return twiml(body)

    response_text, flags = session.respond(user_input)

    # Handle escalation
    if "ESCALATE" in flags:
        escalation_number = CLIENT_CONFIG.get("escalation_number", "")
        body = say(response_text)
        if escalation_number:
            body += f'<Dial>{escalation_number}</Dial>'
        else:
            body += say("I'm sorry, no one is available right now. Please call back during business hours.")
        _log_and_cleanup(CallSid, session)
        return twiml(body)

    # Handle SMS confirmation
    if "SMS_CONFIRM" in flags:
        phone = session.phone
        customer = get_customer_by_phone(phone)
        name = customer["name"] if customer else "there"
        # SMS is sent by voicebot_sms.py - server just sets a flag here
        # The actual SMS call happens in voicebot_sms.py after booking
        pass

    # Handle natural end of call
    if "END_CALL" in flags:
        body = say(response_text)
        body += "<Hangup/>"
        _log_and_cleanup(CallSid, session)
        return twiml(body)

    # Continue conversation
    open_gather, close_gather = gather("/call/respond")
    body = f"{say(response_text)}{open_gather}{say('Go ahead.')}{close_gather}"
    body += say("I didn't hear anything. Feel free to call back anytime. Goodbye!")

    return twiml(body)


# -----------------------------------------------------------------------
# POST /call/transfer - escalate to human
# -----------------------------------------------------------------------

@app.post("/call/transfer")
async def call_transfer(
    CallSid: str = Form(...),
    From: str = Form(...)
):
    escalation_number = CLIENT_CONFIG.get("escalation_number", "")
    body = say("One moment while I transfer you.")
    if escalation_number:
        body += f'<Dial>{escalation_number}</Dial>'
    else:
        body += say("Sorry, no one is available right now. Please call back during business hours.")
    return twiml(body)


# -----------------------------------------------------------------------
# POST /call/complete - call ended, log to CRM
# -----------------------------------------------------------------------

@app.post("/call/complete")
async def call_complete(
    CallSid: str = Form(...),
    From: str = Form(...),
    CallDuration: str = Form(default="0")
):
    session = sessions.get(CallSid)
    if session:
        duration = int(CallDuration) if CallDuration.isdigit() else 0
        session.end_call(duration_seconds=duration)
        sessions.pop(CallSid, None)
        call_start_times.pop(CallSid, None)

    return PlainTextResponse("ok")


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def _log_and_cleanup(call_sid: str, session: VoicebotSession):
    start = call_start_times.get(call_sid)
    duration = int((datetime.now() - start).total_seconds()) if start else 0
    session.end_call(duration_seconds=duration)
    sessions.pop(call_sid, None)
    call_start_times.pop(call_sid, None)


# -----------------------------------------------------------------------
# Health check
# -----------------------------------------------------------------------

@app.get("/")
async def health():
    return {"status": "ok", "business": CLIENT_CONFIG["business_name"]}


# -----------------------------------------------------------------------
# Run
# -----------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8001))
    print(f"Starting voicebot server on port {port}")
    print(f"Business: {CLIENT_CONFIG['business_name']}")
    print(f"Endpoints:")
    print(f"  POST /call/start")
    print(f"  POST /call/respond")
    print(f"  POST /call/transfer")
    print(f"  POST /call/complete")
    uvicorn.run(app, host="0.0.0.0", port=port)
