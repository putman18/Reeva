"""
voicebot_crm.py - SQLite CRM for the AI receptionist

Tables: customers, appointments, calls
Usage: imported by other voicebot modules
"""

import sqlite3
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH = PROJECT_ROOT / ".tmp" / "voicebot" / "crm.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create all tables if they don't exist."""
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT UNIQUE NOT NULL,
            name TEXT,
            email TEXT,
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            service TEXT,
            datetime TEXT,
            status TEXT DEFAULT 'booked',
            calendar_event_id TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER,
            phone TEXT,
            direction TEXT DEFAULT 'inbound',
            duration_seconds INTEGER,
            intent TEXT,
            outcome TEXT,
            summary TEXT,
            transcript TEXT,
            escalated INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        )
    """)
    # Add transcript column if upgrading existing DB
    try:
        c.execute("ALTER TABLE calls ADD COLUMN transcript TEXT")
    except Exception:
        pass

    conn.commit()
    conn.close()
    print(f"DB initialized at {DB_PATH}")


# -----------------------------------------------------------------------
# Customer functions
# -----------------------------------------------------------------------

def get_customer_by_phone(phone: str) -> dict | None:
    """Look up a customer by phone number. Returns dict or None."""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM customers WHERE phone = ?", (phone,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def create_customer(phone: str, name: str = None, email: str = None, notes: str = None) -> dict:
    """Create a new customer record. Returns the created customer."""
    conn = get_conn()
    conn.execute(
        "INSERT INTO customers (phone, name, email, notes) VALUES (?, ?, ?, ?)",
        (phone, name, email, notes)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM customers WHERE phone = ?", (phone,)).fetchone()
    conn.close()
    return dict(row)


def update_customer(phone: str, name: str = None, email: str = None, notes: str = None):
    """Update fields on an existing customer."""
    conn = get_conn()
    if name:
        conn.execute("UPDATE customers SET name = ? WHERE phone = ?", (name, phone))
    if email:
        conn.execute("UPDATE customers SET email = ? WHERE phone = ?", (email, phone))
    if notes:
        conn.execute("UPDATE customers SET notes = ? WHERE phone = ?", (notes, phone))
    conn.commit()
    conn.close()


# -----------------------------------------------------------------------
# Appointment functions
# -----------------------------------------------------------------------

def get_upcoming_appointments(customer_id: int) -> list[dict]:
    """Get all upcoming booked appointments for a customer."""
    conn = get_conn()
    now = datetime.now().isoformat()
    rows = conn.execute(
        """SELECT * FROM appointments
           WHERE customer_id = ? AND status = 'booked' AND datetime > ?
           ORDER BY datetime ASC""",
        (customer_id, now)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def book_appointment(customer_id: int, service: str, dt: str, calendar_event_id: str = None) -> dict:
    """Create a new appointment. dt should be ISO format string."""
    conn = get_conn()
    conn.execute(
        "INSERT INTO appointments (customer_id, service, datetime, status, calendar_event_id) VALUES (?, ?, ?, 'booked', ?)",
        (customer_id, service, dt, calendar_event_id)
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM appointments WHERE customer_id = ? AND datetime = ? ORDER BY id DESC LIMIT 1",
        (customer_id, dt)
    ).fetchone()
    conn.close()
    return dict(row)


def cancel_appointment(appointment_id: int):
    """Mark an appointment as cancelled."""
    conn = get_conn()
    conn.execute(
        "UPDATE appointments SET status = 'cancelled' WHERE id = ?",
        (appointment_id,)
    )
    conn.commit()
    conn.close()


def update_appointment(appointment_id: int, service: str = None, dt: str = None, calendar_event_id: str = None):
    """Update fields on an existing appointment (for reschedule)."""
    conn = get_conn()
    if service:
        conn.execute("UPDATE appointments SET service = ? WHERE id = ?", (service, appointment_id))
    if dt:
        conn.execute("UPDATE appointments SET datetime = ? WHERE id = ?", (dt, appointment_id))
    if calendar_event_id:
        conn.execute("UPDATE appointments SET calendar_event_id = ? WHERE id = ?", (calendar_event_id, appointment_id))
    conn.commit()
    conn.close()


# -----------------------------------------------------------------------
# Call log functions
# -----------------------------------------------------------------------

def log_call(
    phone: str,
    customer_id: int = None,
    duration_seconds: int = None,
    intent: str = None,
    outcome: str = None,
    summary: str = None,
    transcript: str = None,
    escalated: bool = False
) -> dict:
    """Log a completed call to the calls table."""
    conn = get_conn()
    conn.execute(
        """INSERT INTO calls (customer_id, phone, duration_seconds, intent, outcome, summary, transcript, escalated)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (customer_id, phone, duration_seconds, intent, outcome, summary, transcript, int(escalated))
    )
    conn.commit()
    row = conn.execute("SELECT * FROM calls WHERE phone = ? ORDER BY id DESC LIMIT 1", (phone,)).fetchone()
    conn.close()
    return dict(row)


def get_call_history(customer_id: int, limit: int = 5) -> list[dict]:
    """Get recent call history for a customer."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM calls WHERE customer_id = ? ORDER BY created_at DESC LIMIT ?",
        (customer_id, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# -----------------------------------------------------------------------
# Run directly to initialize DB and verify
# -----------------------------------------------------------------------

if __name__ == "__main__":
    init_db()

    # Test: create a customer
    c = create_customer("+17185550001", name="Sarah Johnson", email="sarah@example.com")
    print(f"Created customer: {c['name']} (id={c['id']})")

    # Test: look up by phone
    found = get_customer_by_phone("+17185550001")
    print(f"Looked up: {found['name']}")

    # Test: book appointment
    appt = book_appointment(c["id"], "Haircut", "2026-04-20T14:00:00")
    print(f"Booked: {appt['service']} on {appt['datetime']}")

    # Test: get upcoming
    upcoming = get_upcoming_appointments(c["id"])
    print(f"Upcoming appointments: {len(upcoming)}")

    # Test: log a call
    call = log_call("+17185550001", customer_id=c["id"], duration_seconds=142,
                    intent="book_appointment", outcome="booked", summary="Sarah booked a haircut for April 20 at 2pm.")
    print(f"Call logged: {call['summary']}")

    print("\nAll CRM tests passed.")
