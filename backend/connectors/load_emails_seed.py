"""Load the real starter email sample (db/emails_seed.csv) into your warehouse.

Lets you query real Gmail data in Ganak immediately — before setting up the
Gmail OAuth for the full live sync (gmail_sync.py).

    python load_emails_seed.py
"""
import csv
import os

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:password@localhost:5432/the_balaji")
CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "db", "emails_seed.csv")

DDL = """
CREATE TABLE IF NOT EXISTS emails (
  message_id text PRIMARY KEY, thread_id text, email_date timestamptz,
  sender text, sender_domain text, recipients text, subject text, snippet text,
  direction text, category text, amount numeric, labels text,
  synced_at timestamptz DEFAULT now()
);
"""
UPSERT = """
INSERT INTO emails (message_id, thread_id, email_date, sender, sender_domain,
                    subject, snippet, direction, category, amount, labels)
VALUES %s ON CONFLICT (message_id) DO NOTHING;
"""


def main():
    rows = []
    with open(os.path.abspath(CSV_PATH), newline="") as f:
        for r in csv.DictReader(f):
            rows.append((
                r["message_id"], r["thread_id"], r["email_date"], r["sender"],
                r["sender_domain"], r["subject"], r["snippet"], r["direction"],
                r["category"], (r["amount"] or None), r["labels"],
            ))
    conn = psycopg2.connect(DATABASE_URL)
    conn.set_client_encoding("UTF8")
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(DDL)
        psycopg2.extras.execute_values(cur, UPSERT, rows)
    print(f"✅ Loaded {len(rows)} real starter emails into `emails`. "
          f"Now ask Ganak: \"show payment-received emails over ₹1 lakh\".")


if __name__ == "__main__":
    main()
