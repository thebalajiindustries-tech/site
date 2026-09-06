"""Reproduce the production /ask pipeline locally against Supabase's 'balaji'
schema for an expenses question, and print the FULL traceback instead of the
sanitized 500 message the API returns.

Run from the backend folder: python debug_expenses_ask.py
"""
import os
import sys
import traceback

from dotenv import load_dotenv
load_dotenv(override=True)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import db, llm  # noqa: E402
from app.config import get_settings  # noqa: E402

settings = get_settings()
db_url = settings.SUPABASE_DB_URL
schema = "balaji"

if not db_url:
    print("FAIL: SUPABASE_DB_URL not set in backend/.env")
    sys.exit(1)

questions = [
    "What are my total expenses this quarter?",
    "Break down my expenses by category this quarter",
]

print("Loading schema for 'balaji'...")
try:
    schema_text = db.load_schema(db_url, schema, refresh=True)
    # Print just the expenses table's line(s) so we see real column names/types.
    print()
    print("=== expenses table definition (as Ganak sees it) ===")
    for line in schema_text.splitlines():
        if line.strip().upper().startswith("TABLE EXPENSES"):
            print(line)
    print()
except Exception:
    print("FAIL loading schema:")
    traceback.print_exc()
    sys.exit(1)

for q in questions:
    print(f"--- Question: {q!r} ---")
    try:
        sql = llm.question_to_sql(q, schema_text, dialect="postgres")
        print("Generated SQL:", sql)
        columns, rows = db.run_select(db_url, sql, schema)
        print(f"OK: {len(rows)} row(s), columns={columns}")
        if rows[:3]:
            print("Sample rows:", rows[:3])
    except Exception:
        print("FAILED with traceback:")
        traceback.print_exc()
    print()

print("DONE")
