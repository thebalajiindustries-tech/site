"""One-time migration: copy Balaji's real Zoho warehouse from the local
Postgres database (DATABASE_URL) into the 'balaji' schema of the shared
Supabase project (SUPABASE_DB_URL) -- both read from backend/.env.

Safe to re-run: each table is replaced wholesale in Supabase from the current
local copy, so running it again after a fresh local Zoho sync just refreshes
the cloud copy. It never touches the LOCAL database (read-only there).

Date-like columns are explicitly coerced to real timestamps before the copy.
The local warehouse stores several date columns (e.g. expenses.date) as plain
TEXT, and pandas' default to_sql() faithfully preserves that as TEXT in
Supabase too -- which breaks any SQL Ganak generates that compares the column
with >=/<  against a real date (Postgres has no text >= date operator). This
script fixes that at the source so every date-shaped column lands as a proper
timestamp column in Supabase, regardless of how it's stored locally.
"""
import os
import re
import sys

from dotenv import load_dotenv

load_dotenv(override=True)

from sqlalchemy import create_engine, inspect as sa_inspect, text
import pandas as pd

LOCAL_URL = os.environ.get("DATABASE_URL", "")
SUPA_URL = os.environ.get("SUPABASE_DB_URL", "")
SCHEMA = "balaji"

if not LOCAL_URL or not LOCAL_URL.startswith("postgres"):
    print("FAIL: DATABASE_URL in backend/.env is not a Postgres URL -- nothing to migrate from.")
    sys.exit(1)
if not SUPA_URL:
    print("FAIL: SUPABASE_DB_URL not set in backend/.env")
    sys.exit(1)

print(f"Local source:  DATABASE_URL (len={len(LOCAL_URL)})")
print(f"Cloud target:  SUPABASE_DB_URL (len={len(SUPA_URL)}), schema '{SCHEMA}'")
print()

local = create_engine(LOCAL_URL)
supa = create_engine(SUPA_URL)

insp = sa_inspect(local)
tables = [
    t for t in insp.get_table_names(schema="public")
    if not t.startswith("pg_") and t != "sync_metadata"
]
if not tables:
    print("No tables found in the local 'public' schema -- nothing to migrate.")
    sys.exit(0)
print(f"Found {len(tables)} table(s) locally: {', '.join(tables)}")
print()

with supa.connect() as c:
    c.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"'))
    c.commit()

# Columns that look like they hold a date/datetime, whatever their stored type.
_DATE_NAME_RE = re.compile(
    r"(^date$)|(_date$)|(^date_)|(_time$)|(^created_time$)|(^last_modified_time$)",
    re.IGNORECASE,
)


def _coerce_date_columns(df: "pd.DataFrame", table: str) -> list[str]:
    """Convert date-shaped columns to real datetimes in place. Returns the
    list of columns that were converted, for the printed report."""
    converted = []
    for col in df.columns:
        if not _DATE_NAME_RE.search(col):
            continue
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            continue  # already a real datetime (e.g. came in as timestamp)
        non_null = df[col].notna().sum()
        if non_null == 0:
            continue
        parsed = pd.to_datetime(df[col], errors="coerce", utc=False)
        parsed_non_null = parsed.notna().sum()
        # Only trust the conversion if the vast majority of values parsed --
        # guards against a column whose name merely contains "date"/"time"
        # but isn't actually one (rare, but cheap to check).
        if parsed_non_null >= 0.9 * non_null:
            df[col] = parsed
            converted.append(col)
    return converted


total_rows = 0
for t in tables:
    df = pd.read_sql_table(t, local, schema="public")
    n = len(df)
    if n == 0:
        print(f"  {t}: 0 rows, skipping")
        continue
    converted = _coerce_date_columns(df, t)
    df.to_sql(t, supa, schema=SCHEMA, if_exists="replace", index=False,
              method="multi", chunksize=500)
    total_rows += n
    extra = f"  [fixed date columns: {', '.join(converted)}]" if converted else ""
    print(f"  {t}: copied {n} rows{extra}")

print()
print(f"DONE. Copied {total_rows} rows across {len(tables)} table(s) into Supabase schema '{SCHEMA}'.")
print("Restart Ganak (start.bat) so it picks up the fresh data.")
