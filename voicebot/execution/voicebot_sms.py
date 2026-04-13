"""
voicebot_sms.py - Send SMS confirmations and reminders via Twilio

Functions:
    send_confirmation()  - Send booking confirmation after appointment is made
    send_reminder()      - Send reminder 24 hours before appointment
    send_cancellation()  - Send cancellation confirmation
"""

import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from twilio.rest import Client
from datetime import datetime

ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
FROM_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")

CLIENT_CONFIG = {
    "business_name": "Mario's Barber Shop",
    "business_phone": FROM_NUMBER
}


def get_client() -> Client:
    return Client(ACCOUNT_SID, AUTH_TOKEN)


def format_dt(dt_str: str) -> str:
    """Format ISO datetime string to human readable: Thu Apr 17 at 2:00 PM"""
    try:
        dt = datetime.fromisoformat(dt_str)
        return dt.strftime("%a %b %#d at %#I:%M %p")
    except Exception:
        return dt_str


def send_confirmation(to_phone: str, customer_name: str, service: str, dt_str: str) -> bool:
    """
    Send a booking confirmation text.
    Returns True on success, False on failure.
    """
    business = CLIENT_CONFIG["business_name"]
    dt_label = format_dt(dt_str)
    first_name = customer_name.split()[0] if customer_name else "there"

    body = (
        f"Hi {first_name}, your {service} at {business} is confirmed for {dt_label}. "
        f"Reply CANCEL to cancel. See you then!"
    )

    try:
        client = get_client()
        client.messages.create(body=body, from_=FROM_NUMBER, to=to_phone)
        print(f"Confirmation sent to {to_phone}")
        return True
    except Exception as e:
        print(f"SMS failed: {e}")
        return False


def send_reminder(to_phone: str, customer_name: str, service: str, dt_str: str) -> bool:
    """
    Send a reminder text 24 hours before the appointment.
    Returns True on success, False on failure.
    """
    business = CLIENT_CONFIG["business_name"]
    dt_label = format_dt(dt_str)
    first_name = customer_name.split()[0] if customer_name else "there"

    body = (
        f"Reminder: {first_name}, your {service} at {business} is tomorrow, {dt_label}. "
        f"Reply CANCEL to cancel."
    )

    try:
        client = get_client()
        client.messages.create(body=body, from_=FROM_NUMBER, to=to_phone)
        print(f"Reminder sent to {to_phone}")
        return True
    except Exception as e:
        print(f"SMS failed: {e}")
        return False


def send_cancellation(to_phone: str, customer_name: str, service: str, dt_str: str) -> bool:
    """
    Send a cancellation confirmation text.
    Returns True on success, False on failure.
    """
    business = CLIENT_CONFIG["business_name"]
    dt_label = format_dt(dt_str)
    first_name = customer_name.split()[0] if customer_name else "there"

    body = (
        f"Hi {first_name}, your {service} at {business} on {dt_label} has been cancelled. "
        f"Call us to rebook anytime."
    )

    try:
        client = get_client()
        client.messages.create(body=body, from_=FROM_NUMBER, to=to_phone)
        print(f"Cancellation SMS sent to {to_phone}")
        return True
    except Exception as e:
        print(f"SMS failed: {e}")
        return False


# -----------------------------------------------------------------------
# Run directly to test
# -----------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    test_phone = sys.argv[1] if len(sys.argv) > 1 else input("Enter your phone number to test (e.g. +17185551234): ").strip()

    print(f"\nSending test confirmation to {test_phone}...")
    ok = send_confirmation(
        to_phone=test_phone,
        customer_name="Jake Rivera",
        service="Haircut",
        dt_str="2026-04-19T09:00:00"
    )

    if ok:
        print("SMS sent. Check your phone.")
    else:
        print("SMS failed. Check your Twilio credentials and phone number.")
