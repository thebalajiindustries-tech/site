"""
Gmail -> PostgreSQL connector for Ganak.

Pulls Balaji's finance emails (payments received, bank advices, vendor bills,
balance confirmations, quotations, POs) into an `emails` table so the AI can
answer questions across Zoho data AND email — e.g. "find the payment-received
email from OJAS" or "which vendors sent balance confirmations this year".

Same spirit as your zoho_postgres_sync.py: run it on a schedule; it only
appends/updates, never deletes.

Setup (one time):
  1) Google Cloud console -> enable Gmail API -> create OAuth client (Desktop app)
     -> download credentials.json into this folder.
  2) pip install -r requirements-gmail.txt
  3) python gmail_sync.py full        # opens a browser once to authorize, stores token.json

Usage:
  python gmail_sync.py full           # last 12 months (configurable)
  python gmail_sync.py incremental    # only messages newer than the last sync
"""
import os
import sys
import base64
import datetime as dt

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

from classify import classify, parse_amount, sender_domain, direction

load_dotenv()

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:password@localhost:5432/the_balaji"
)
# emails matching this Gmail query are considered "finance" emails
FINANCE_QUERY = os.environ.get(
    "GMAIL_QUERY",
    'invoice OR payment OR receipt OR "amount due" OR "balance confirmation" '
    'OR quotation OR "purchase order" OR bill',
)
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
HERE = os.path.dirname(os.path.abspath(__file__))


# ------------------------- Gmail auth + fetch -------------------------
def gmail_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    token_path = os.path.join(HERE, "token.json")
    cred_path = os.path.join(HERE, "credentials.json")
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(cred_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def header(headers, name):
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def fetch_messages(svc, query, max_messages=2000):
    """Yield lightweight message dicts matching the query."""
    page_token = None
    fetched = 0
    while True:
        resp = svc.users().messages().list(
            userId="me", q=query, pageToken=page_token, maxResults=100
        ).execute()
        for m in resp.get("messages", []):
            full = svc.users().messages().get(
                userId="me", id=m["id"], format="metadata",
                metadataHeaders=["From", "To", "Subject", "Date"],
            ).execute()
            headers = full.get("payload", {}).get("headers", [])
            yield {
                "message_id": full["id"],
                "thread_id": full["threadId"],
                "sender": header(headers, "From"),
                "recipients": header(headers, "To"),
                "subject": header(headers, "Subject"),
                "snippet": full.get("snippet", ""),
                "internal_date": int(full.get("internalDate", "0")),
                "label_ids": full.get("labelIds", []),
            }
            fetched += 1
            if fetched >= max_messages:
                return
        page_token = resp.get("nextPageToken")
        if not page_token:
            return


# ------------------------- database -------------------------
DDL = """
CREATE TABLE IF NOT EXISTS emails (
  message_id    text PRIMARY KEY,
  thread_id     text,
  email_date    timestamptz,
  sender        text,
  sender_domain text,
  recipients    text,
  subject       text,
  snippet       text,
  direction     text,
  category      text,
  amount        numeric,
  labels        text,
  synced_at     timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS emails_category_idx ON emails(category);
CREATE INDEX IF NOT EXISTS emails_date_idx     ON emails(email_date);
"""

UPSERT = """
INSERT INTO emails (message_id, thread_id, email_date, sender, sender_domain,
                    recipients, subject, snippet, direction, category, amount, labels)
VALUES %s
ON CONFLICT (message_id) DO UPDATE SET
  category = EXCLUDED.category, amount = EXCLUDED.amount, labels = EXCLUDED.labels,
  synced_at = now();
"""


def to_row(m):
    date = dt.datetime.fromtimestamp(m["internal_date"] / 1000, tz=dt.timezone.utc)
    return (
        m["message_id"], m["thread_id"], date, m["sender"], sender_domain(m["sender"]),
        m["recipients"], m["subject"], m["snippet"],
        direction(m["sender"], m["label_ids"]),
        classify(m["sender"], m["subject"], m["snippet"]),
        parse_amount(m["subject"]) or parse_amount(m["snippet"]),
        ",".join(m["label_ids"]),
    )


def sync(mode="full"):
    conn = psycopg2.connect(DATABASE_URL)
    conn.set_client_encoding("UTF8")
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(DDL)

    query = FINANCE_QUERY
    if mode == "incremental":
        with conn.cursor() as cur:
            cur.execute("SELECT max(email_date) FROM emails;")
            last = cur.fetchone()[0]
        if last:
            query += f" after:{int(last.timestamp())}"
    else:
        query += " newer_than:1y"

    svc = gmail_service()
    rows, n = [], 0
    for m in fetch_messages(svc, query):
        rows.append(to_row(m))
        n += 1
        if len(rows) >= 200:
            _flush(conn, rows); rows = []
    if rows:
        _flush(conn, rows)
    print(f"✅ Synced {n} finance emails to `emails`.")


def _flush(conn, rows):
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, UPSERT, rows)
    print(f"  … wrote {len(rows)} rows")


if __name__ == "__main__":
    sync(sys.argv[1] if len(sys.argv) > 1 else "full")
