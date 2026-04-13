"""
voicebot_calendar.py - Google Calendar integration for the AI receptionist

Functions:
    get_available_slots()  - list open time slots in a date range
    book_slot()            - create a calendar event, return event ID
    cancel_slot()          - delete a calendar event by event ID
    reschedule_slot()      - cancel old event, book new one

Setup:
    1. Go to console.cloud.google.com
    2. Create project > Enable Google Calendar API
    3. Credentials > OAuth 2.0 Client ID > Desktop app > Download JSON
    4. Save as credentials.json in Projects root
    5. Run this file once to authenticate: python voicebot/execution/voicebot_calendar.py
"""

import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

PROJECT_ROOT = Path(__file__).parent.parent.parent
VOICEBOT_ROOT = Path(__file__).parent.parent
CREDENTIALS_FILE = VOICEBOT_ROOT / "credentials.json"
TOKEN_FILE = VOICEBOT_ROOT / "token.json"
SCOPES = ["https://www.googleapis.com/auth/calendar"]


def get_service():
    """Authenticate and return a Google Calendar service object."""
    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    f"credentials.json not found at {CREDENTIALS_FILE}\n"
                    "Steps to fix:\n"
                    "  1. Go to console.cloud.google.com\n"
                    "  2. Create project > Enable Google Calendar API\n"
                    "  3. Credentials > OAuth 2.0 Client ID > Desktop app > Download JSON\n"
                    "  4. Save as credentials.json in your Projects root folder\n"
                    "  5. Run this file again to authenticate"
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)

        TOKEN_FILE.write_text(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def get_available_slots(
    calendar_id: str = "primary",
    days_ahead: int = 7,
    slot_duration_minutes: int = 30,
    business_hours: tuple = (9, 18),
    max_slots: int = 6
) -> list[dict]:
    """
    Return available time slots for the next N days during business hours.

    Returns list of dicts: [{"start": "2026-04-15T10:00:00", "end": "...", "label": "Tue Apr 15 at 10:00 AM"}]
    """
    service = get_service()

    now = datetime.now(timezone.utc)
    time_min = now.isoformat()
    time_max = (now + timedelta(days=days_ahead)).isoformat()

    # Get busy times from Google Calendar
    body = {
        "timeMin": time_min,
        "timeMax": time_max,
        "items": [{"id": calendar_id}]
    }
    freebusy = service.freebusy().query(body=body).execute()
    busy_periods = freebusy["calendars"][calendar_id]["busy"]

    busy_ranges = [
        (datetime.fromisoformat(b["start"].replace("Z", "+00:00")),
         datetime.fromisoformat(b["end"].replace("Z", "+00:00")))
        for b in busy_periods
    ]

    slots = []
    cursor = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

    while len(slots) < max_slots and cursor < now + timedelta(days=days_ahead):
        # Skip outside business hours
        if cursor.hour < business_hours[0] or cursor.hour >= business_hours[1]:
            if cursor.hour >= business_hours[1]:
                cursor = (cursor + timedelta(days=1)).replace(hour=business_hours[0], minute=0)
            else:
                cursor = cursor.replace(hour=business_hours[0], minute=0)
            continue

        # Skip weekends (0=Mon, 6=Sun)
        if cursor.weekday() >= 5:
            cursor = (cursor + timedelta(days=1)).replace(hour=business_hours[0], minute=0)
            continue

        slot_end = cursor + timedelta(minutes=slot_duration_minutes)

        # Check if slot overlaps with any busy period
        is_busy = any(
            not (slot_end <= b_start or cursor >= b_end)
            for b_start, b_end in busy_ranges
        )

        if not is_busy:
            local_start = cursor.astimezone()
            slots.append({
                "start": local_start.strftime("%Y-%m-%dT%H:%M:%S"),
                "end": (local_start + timedelta(minutes=slot_duration_minutes)).strftime("%Y-%m-%dT%H:%M:%S"),
                "label": local_start.strftime("%a %b %#d at %#I:%M %p")
            })

        cursor += timedelta(minutes=slot_duration_minutes)

    return slots


def book_slot(
    calendar_id: str,
    customer_name: str,
    service: str,
    start_dt: str,
    end_dt: str,
    customer_phone: str = None,
    notes: str = None
) -> str:
    """
    Create a Google Calendar event and return the event ID.

    start_dt / end_dt: ISO format strings like "2026-04-15T10:00:00"
    """
    service_obj = get_service()

    description = f"Service: {service}"
    if customer_phone:
        description += f"\nPhone: {customer_phone}"
    if notes:
        description += f"\nNotes: {notes}"

    event = {
        "summary": f"{service} - {customer_name}",
        "description": description,
        "start": {"dateTime": start_dt, "timeZone": "America/New_York"},
        "end": {"dateTime": end_dt, "timeZone": "America/New_York"},
    }

    created = service_obj.events().insert(calendarId=calendar_id, body=event).execute()
    return created["id"]


def cancel_slot(calendar_id: str, event_id: str):
    """Delete a Google Calendar event by event ID."""
    service = get_service()
    service.events().delete(calendarId=calendar_id, eventId=event_id).execute()


def reschedule_slot(
    calendar_id: str,
    old_event_id: str,
    customer_name: str,
    service: str,
    new_start_dt: str,
    new_end_dt: str,
    customer_phone: str = None
) -> str:
    """Cancel old event and book a new one. Returns new event ID."""
    cancel_slot(calendar_id, old_event_id)
    return book_slot(calendar_id, customer_name, service, new_start_dt, new_end_dt, customer_phone)


# -----------------------------------------------------------------------
# Run directly to authenticate and test
# -----------------------------------------------------------------------

if __name__ == "__main__":
    print("Connecting to Google Calendar...")
    try:
        slots = get_available_slots(days_ahead=7, max_slots=3)
        print(f"\nFound {len(slots)} available slots:")
        for s in slots:
            print(f"  {s['label']}  ({s['start']})")
        print("\nGoogle Calendar connected successfully.")
    except FileNotFoundError as e:
        print(f"\nSetup required:\n{e}")
    except Exception as e:
        print(f"\nError: {e}")
