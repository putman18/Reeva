"""
read_sheet.py - Read rows from a Google Sheet and output as JSON.

Usage:
    python execution/read_sheet.py \
        --sheet-id SPREADSHEET_ID \
        --range "Sheet1!A1:Z" \
        [--output .tmp/output.json]

Environment variables required:
    GOOGLE_CREDENTIALS_FILE, GOOGLE_TOKEN_FILE

OAuth setup: run once interactively to generate token.json.
Subsequent runs are headless.
"""

import argparse
import json
import os
import sys

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def get_credentials() -> Credentials:
    creds_file = os.environ.get("GOOGLE_CREDENTIALS_FILE", "credentials.json")
    token_file = os.environ.get("GOOGLE_TOKEN_FILE", "token.json")

    creds = None
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_file, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, "w") as f:
            f.write(creds.to_json())

    return creds


def read_sheet(sheet_id: str, range_name: str) -> list[dict]:
    creds = get_credentials()
    service = build("sheets", "v4", credentials=creds)
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=sheet_id, range=range_name)
        .execute()
    )

    rows = result.get("values", [])
    if not rows:
        return []

    headers = rows[0]
    return [dict(zip(headers, row)) for row in rows[1:]]


def main():
    parser = argparse.ArgumentParser(description="Read rows from a Google Sheet")
    parser.add_argument("--sheet-id", required=True, help="Google Spreadsheet ID")
    parser.add_argument("--range", required=True, help='Range, e.g. "Sheet1!A1:Z"')
    parser.add_argument("--output", help="Output JSON file path (default: stdout)")
    args = parser.parse_args()

    data = read_sheet(args.sheet_id, args.range)

    output = json.dumps(data, indent=2)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output)
        print(f"Wrote {len(data)} rows to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
