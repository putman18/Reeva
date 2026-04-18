"""
voicebot_agent.py - Claude conversation logic for the AI receptionist

Handles the full call flow:
- Greet by name if existing customer, generic if new
- Classify intent: book, reschedule, cancel, question, escalate
- Use tools to check calendar, book/cancel appointments, update CRM
- Return TwiML-ready responses at each turn
"""

import json
import os
import urllib.request
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_APPOINTMENTS_CHANNEL = "1493074033938268330"


def notify_discord_appointment(customer_name: str, phone: str, service: str, dt: str):
    """Fire a Discord message to #voicebot-appointments when a booking is made."""
    try:
        from datetime import datetime
        dt_label = datetime.fromisoformat(dt).strftime("%a %b %#d at %#I:%M %p")
    except Exception:
        dt_label = dt

    message = (
        f"**New Appointment Booked**\n"
        f"**Customer:** {customer_name}\n"
        f"**Phone:** {phone}\n"
        f"**Service:** {service}\n"
        f"**Time:** {dt_label}"
    )

    try:
        data = json.dumps({"content": message}).encode()
        req = urllib.request.Request(
            f"https://discord.com/api/v10/channels/{DISCORD_APPOINTMENTS_CHANNEL}/messages",
            data=data,
            headers={
                "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
                "Content-Type": "application/json",
                "User-Agent": "DiscordBot (voicebot, 1.0)"
            },
            method="POST"
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"Discord notify failed: {e}")

import anthropic
from datetime import datetime
from voicebot_crm import (
    get_customer_by_phone, create_customer, update_customer,
    get_upcoming_appointments, book_appointment, cancel_appointment,
    update_appointment, log_call
)
from voicebot_calendar import get_available_slots, book_slot, cancel_slot, reschedule_slot

# -----------------------------------------------------------------------
# Client config - swap this per business
# -----------------------------------------------------------------------

CLIENT_CONFIG = {
    "business_name": "Mario's Barber Shop",
    "hours": "Monday through Saturday, 9am to 7pm, closed Sunday",
    "address": "123 Main Street, Staten Island, New York",
    "services": {
        "haircut": "$25",
        "beard trim": "$15",
        "haircut and beard": "$35"
    },
    "faqs": {
        "do you take walk ins": "Yes, based on availability",
        "do you accept cards": "Yes, all major cards accepted",
        "do you take appointments": "Yes, we take appointments by phone"
    },
    "escalation_number": "+17185550000",
    "calendar_id": "primary",
    "slot_duration_minutes": 30,
    "booking_buffer_days": 14
}

# -----------------------------------------------------------------------
# Tool definitions for Claude
# -----------------------------------------------------------------------

TOOLS = [
    {
        "name": "lookup_customer",
        "description": "Look up a customer by phone number to get their name and appointment history.",
        "input_schema": {
            "type": "object",
            "properties": {
                "phone": {"type": "string", "description": "E.164 phone number e.g. +17185551234"}
            },
            "required": ["phone"]
        }
    },
    {
        "name": "get_available_slots",
        "description": "Get available appointment slots for the next 14 days.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days_ahead": {"type": "integer", "description": "How many days ahead to search (default 7)"}
            },
            "required": []
        }
    },
    {
        "name": "book_appointment",
        "description": "Book an appointment for the customer in the calendar and CRM.",
        "input_schema": {
            "type": "object",
            "properties": {
                "phone": {"type": "string", "description": "Customer phone number"},
                "customer_name": {"type": "string", "description": "Customer full name"},
                "service": {"type": "string", "description": "Service being booked e.g. Haircut"},
                "start_dt": {"type": "string", "description": "Start datetime ISO format e.g. 2026-04-15T10:00:00"},
                "end_dt": {"type": "string", "description": "End datetime ISO format e.g. 2026-04-15T10:30:00"}
            },
            "required": ["phone", "customer_name", "service", "start_dt", "end_dt"]
        }
    },
    {
        "name": "cancel_appointment",
        "description": "Cancel the customer's upcoming appointment.",
        "input_schema": {
            "type": "object",
            "properties": {
                "phone": {"type": "string", "description": "Customer phone number"},
                "appointment_id": {"type": "integer", "description": "Appointment ID from CRM"}
            },
            "required": ["phone", "appointment_id"]
        }
    },
    {
        "name": "reschedule_appointment",
        "description": "Cancel the old appointment and book a new one.",
        "input_schema": {
            "type": "object",
            "properties": {
                "phone": {"type": "string", "description": "Customer phone number"},
                "customer_name": {"type": "string", "description": "Customer full name"},
                "old_appointment_id": {"type": "integer", "description": "Appointment ID to cancel"},
                "old_calendar_event_id": {"type": "string", "description": "Google Calendar event ID to cancel"},
                "service": {"type": "string", "description": "Service being booked"},
                "new_start_dt": {"type": "string", "description": "New start datetime ISO format"},
                "new_end_dt": {"type": "string", "description": "New end datetime ISO format"}
            },
            "required": ["phone", "customer_name", "old_appointment_id", "service", "new_start_dt", "new_end_dt"]
        }
    },
    {
        "name": "get_upcoming_appointments",
        "description": "Get the customer's upcoming booked appointments from the CRM.",
        "input_schema": {
            "type": "object",
            "properties": {
                "phone": {"type": "string", "description": "Customer phone number"}
            },
            "required": ["phone"]
        }
    }
]

# -----------------------------------------------------------------------
# Tool execution
# -----------------------------------------------------------------------

def run_tool(tool_name: str, tool_input: dict) -> str:
    config = CLIENT_CONFIG

    if tool_name == "lookup_customer":
        customer = get_customer_by_phone(tool_input["phone"])
        if customer:
            appointments = get_upcoming_appointments(customer["id"])
            return json.dumps({
                "found": True,
                "customer": customer,
                "upcoming_appointments": appointments
            })
        return json.dumps({"found": False})

    elif tool_name == "get_available_slots":
        days = tool_input.get("days_ahead", config["booking_buffer_days"])
        slots = get_available_slots(
            calendar_id=config["calendar_id"],
            days_ahead=days,
            slot_duration_minutes=config["slot_duration_minutes"]
        )
        return json.dumps({"slots": slots})

    elif tool_name == "book_appointment":
        phone = tool_input["phone"]
        customer = get_customer_by_phone(phone)
        if not customer:
            customer = create_customer(phone, name=tool_input["customer_name"])

        event_id = book_slot(
            calendar_id=config["calendar_id"],
            customer_name=tool_input["customer_name"],
            service=tool_input["service"],
            start_dt=tool_input["start_dt"],
            end_dt=tool_input["end_dt"],
            customer_phone=phone
        )

        appt = book_appointment(
            customer_id=customer["id"],
            service=tool_input["service"],
            dt=tool_input["start_dt"],
            calendar_event_id=event_id
        )

        notify_discord_appointment(tool_input["customer_name"], phone, tool_input["service"], tool_input["start_dt"])
        return json.dumps({"success": True, "appointment": appt, "calendar_event_id": event_id})

    elif tool_name == "cancel_appointment":
        phone = tool_input["phone"]
        appt_id = tool_input["appointment_id"]

        customer = get_customer_by_phone(phone)
        if customer:
            appointments = get_upcoming_appointments(customer["id"])
            appt = next((a for a in appointments if a["id"] == appt_id), None)
            if appt and appt.get("calendar_event_id"):
                cancel_slot(config["calendar_id"], appt["calendar_event_id"])

        cancel_appointment(appt_id)
        return json.dumps({"success": True})

    elif tool_name == "reschedule_appointment":
        phone = tool_input["phone"]
        old_event_id = tool_input.get("old_calendar_event_id")

        if old_event_id:
            new_event_id = reschedule_slot(
                calendar_id=config["calendar_id"],
                old_event_id=old_event_id,
                customer_name=tool_input["customer_name"],
                service=tool_input["service"],
                new_start_dt=tool_input["new_start_dt"],
                new_end_dt=tool_input["new_end_dt"],
                customer_phone=phone
            )
        else:
            new_event_id = book_slot(
                calendar_id=config["calendar_id"],
                customer_name=tool_input["customer_name"],
                service=tool_input["service"],
                start_dt=tool_input["new_start_dt"],
                end_dt=tool_input["new_end_dt"],
                customer_phone=phone
            )

        cancel_appointment(tool_input["old_appointment_id"])

        customer = get_customer_by_phone(phone)
        new_appt = book_appointment(
            customer_id=customer["id"],
            service=tool_input["service"],
            dt=tool_input["new_start_dt"],
            calendar_event_id=new_event_id
        )

        return json.dumps({"success": True, "new_appointment": new_appt})

    elif tool_name == "get_upcoming_appointments":
        customer = get_customer_by_phone(tool_input["phone"])
        if not customer:
            return json.dumps({"appointments": []})
        appointments = get_upcoming_appointments(customer["id"])
        return json.dumps({"appointments": appointments})

    return json.dumps({"error": f"Unknown tool: {tool_name}"})


# -----------------------------------------------------------------------
# System prompt builder
# -----------------------------------------------------------------------

def build_system_prompt(customer: dict | None, phone: str) -> str:
    config = CLIENT_CONFIG
    now = datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")

    services_list = "\n".join(
        f"  - {svc.title()}: {price}"
        for svc, price in config["services"].items()
    )

    faqs_list = "\n".join(
        f"  Q: {q}\n  A: {a}"
        for q, a in config["faqs"].items()
    )

    if customer:
        identity = f"You are speaking with {customer['name']} (returning customer, phone: {phone})."
        if customer.get("notes"):
            identity += f" Notes about this customer: {customer['notes']}"
    else:
        identity = f"This is a new caller (phone: {phone}). You do not know their name yet - collect it naturally during the conversation."

    return f"""You are the AI receptionist for {config['business_name']}. You answer calls, schedule appointments, and help customers.

Today is {now}.
{identity}

Business hours: {config['hours']}
Address: {config['address']}

Services and pricing:
{services_list}

FAQs:
{faqs_list}

Rules:
- Be warm, friendly, and concise. You are speaking on a phone call - keep responses short and natural.
- Never read out long lists. Offer 2-3 options at a time.
- If the customer wants to speak to a human, say: "Let me transfer you now." and include [ESCALATE] at the end of your response.
- If you just confirmed a booking or reschedule, include [SMS_CONFIRM] at the end so a confirmation text is sent.
- If the call is ending naturally, include [END_CALL] at the end of your response.
- Always confirm appointment details before booking (service, date, time).
- Use your tools to check real availability before offering slots.
- Do not make up availability - always call get_available_slots first."""


# -----------------------------------------------------------------------
# Main conversation handler
# -----------------------------------------------------------------------

class VoicebotSession:
    def __init__(self, phone: str):
        self.phone = phone
        self.messages = []
        self.customer = get_customer_by_phone(phone)
        self.call_start = datetime.now()
        self.intent = None
        self.outcome = None
        self.escalated = False
        self.client = anthropic.Anthropic()

    def get_opening_greeting(self) -> str:
        config = CLIENT_CONFIG
        if self.customer:
            name = self.customer["name"].split()[0]
            return f"Hi {name}, thanks for calling {config['business_name']}. How can I help you today?"
        return f"Thanks for calling {config['business_name']}, how can I help you today?"

    def respond(self, user_input: str) -> tuple[str, list[str]]:
        """
        Process one turn of the conversation.
        Returns (response_text, flags) where flags can include ESCALATE, SMS_CONFIRM, END_CALL.
        """
        self.messages.append({"role": "user", "content": user_input})

        system = build_system_prompt(self.customer, self.phone)

        response = self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=system,
            tools=TOOLS,
            messages=self.messages
        )

        # Handle tool calls in a loop
        while response.stop_reason == "tool_use":
            tool_results = []
            assistant_content = response.content

            for block in response.content:
                if block.type == "tool_use":
                    result = run_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result
                    })

            self.messages.append({"role": "assistant", "content": assistant_content})
            self.messages.append({"role": "user", "content": tool_results})

            response = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=512,
                system=system,
                tools=TOOLS,
                messages=self.messages
            )

        # Extract text response
        text = ""
        for block in response.content:
            if hasattr(block, "text"):
                text += block.text

        self.messages.append({"role": "assistant", "content": text})

        # Parse flags
        flags = []
        for flag in ["ESCALATE", "SMS_CONFIRM", "END_CALL"]:
            if f"[{flag}]" in text:
                flags.append(flag)
                text = text.replace(f"[{flag}]", "").strip()

        if "ESCALATE" in flags:
            self.escalated = True

        return text, flags

    def end_call(self, duration_seconds: int = None):
        """Log the call to CRM with a summary."""
        if not self.messages:
            return

        # Build a plain text transcript for summarization
        transcript = ""
        for msg in self.messages:
            if isinstance(msg["content"], str):
                role = "Customer" if msg["role"] == "user" else "Bot"
                transcript += f"{role}: {msg['content']}\n"

        # Generate summary using Claude
        summary_response = self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            messages=[
                {
                    "role": "user",
                    "content": f"Summarize this call in 1-2 sentences:\n\n{transcript}"
                }
            ]
        )
        summary = summary_response.content[0].text if summary_response.content else ""

        customer = get_customer_by_phone(self.phone)
        log_call(
            phone=self.phone,
            customer_id=customer["id"] if customer else None,
            duration_seconds=duration_seconds,
            intent=self.intent,
            outcome=self.outcome,
            summary=summary,
            transcript=transcript,
            escalated=self.escalated
        )


# -----------------------------------------------------------------------
# Run directly to test conversation in terminal
# -----------------------------------------------------------------------

if __name__ == "__main__":
    print("=== Voicebot Agent Test ===")
    print("Simulating call from +17185559999 (new customer)\n")

    session = VoicebotSession("+17185559999")
    print(f"Bot: {session.get_opening_greeting()}\n")

    test_inputs = [
        "Hi I'd like to book a haircut",
        "Saturday works, morning if possible",
        "The first one is fine",
        "My name is Jake Rivera",
        "That's all, thanks"
    ]

    for user_input in test_inputs:
        print(f"User: {user_input}")
        response, flags = session.respond(user_input)
        print(f"Bot: {response}")
        if flags:
            print(f"Flags: {flags}")
        print()

    session.end_call(duration_seconds=180)
    print("Call logged to CRM.")
