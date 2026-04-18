"""
update_sheet.py - Write rows to a Google Sheet.

Usage:
    python execution/update_sheet.py \
        --sheet-id SPREADSHEET_ID \
        --range "Sheet1!A1" \
        --data '[["Col1", "Col2"], ["val1", "val2"]]'

    Or pipe JSON from a file:
        python execution/update_sheet.py \
            --sheet-id SPREADSHEET_ID \
            --range "Sheet1!A1" \
            --data-file .tmp/rows.json

Environment variables required:
    GOOGLE_CREDENTIALS_FILE, GOOGLE_TOKEN_FILE
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

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


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


def update_sheet(sheet_id: str, range_name: str, values: list[list]) -> dict:
    creds = get_credentials()
    service = build("sheets", "v4", credentials=creds)

    body = {"values": values}
    result = (
        service.spreadsheets()
        .values()
        .update(
            spreadsheetId=sheet_id,
            range=range_name,
            valueInputOption="USER_ENTERED",
            body=body,
        )
        .execute()
    )
    return result


def main():
    parser = argparse.ArgumentParser(description="Write rows to a Google Sheet")
    parser.add_argument("--sheet-id", required=True, help="Google Spreadsheet ID")
    parser.add_argument("--range", required=True, help='Start range, e.g. "Sheet1!A1"')

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--data", help="JSON array of arrays")
    group.add_argument("--data-file", help="Path to JSON file with array of arrays")

    args = parser.parse_args()

    if args.data_file:
        with open(args.data_file) as f:
            values = json.load(f)
    else:
        values = json.loads(args.data)

    result = update_sheet(args.sheet_id, args.range, values)
    updated = result.get("updatedCells", 0)
    print(f"Updated {updated} cells in {args.range}")


if __name__ == "__main__":
    main()
