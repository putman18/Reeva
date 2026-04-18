"""
send_email.py - Send an email via SMTP.

Usage:
    python execution/send_email.py \
        --to recipient@example.com \
        --subject "Subject line" \
        --body "Email body text" \
        [--html]  # treat body as HTML

Environment variables required:
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD
"""

import argparse
import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dotenv import load_dotenv

load_dotenv()


def send_email(to: str, subject: str, body: str, html: bool = False) -> None:
    host = os.environ["SMTP_HOST"]
    port = int(os.environ["SMTP_PORT"])
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASSWORD"]

    msg = MIMEMultipart("alternative")
    msg["From"] = user
    msg["To"] = to
    msg["Subject"] = subject

    mime_type = "html" if html else "plain"
    msg.attach(MIMEText(body, mime_type))

    with smtplib.SMTP(host, port) as server:
        server.ehlo()
        server.starttls()
        server.login(user, password)
        server.sendmail(user, to, msg.as_string())

    print(f"Email sent to {to}")


def main():
    parser = argparse.ArgumentParser(description="Send an email via SMTP")
    parser.add_argument("--to", required=True, help="Recipient email address")
    parser.add_argument("--subject", required=True, help="Email subject")
    parser.add_argument("--body", required=True, help="Email body")
    parser.add_argument("--html", action="store_true", help="Treat body as HTML")
    args = parser.parse_args()

    send_email(args.to, args.subject, args.body, args.html)


if __name__ == "__main__":
    main()
