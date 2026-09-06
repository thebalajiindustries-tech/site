"""One-off check: what tables/rows exist in the LOCAL Postgres warehouse
(DATABASE_URL in backend/.env) that Ganak's migration script reads from.

Run this from the backend folder (same place as .env), on your actual
Windows machine (not the cloud sandbox) so it can reach localhost Postgres.
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv(override=True)

url = os.environ.get("DATABASE_URL", "")
if not url or not url.startswith("postgres"):
    print("FAIL: DATABASE_URL in backend/.env is not set to a Postgres URL.")
    sys.exit(1)

try:
    import psycopg2
except ImportError:
    os.system(f"{sys.executable} -m pip install --quiet psycopg2-binary")
    import psycopg2

try:
    conn = psycopg2.connect(url, connect_timeout=10)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name NOT LIKE 'pg_%'
        ORDER BY table_name;
        """
    )
    tables = [r[0] for r in cur.fetchall()]
    print(f"Tables in local 'public' schema: {tables}")
    print()
    for t in tables:
        cur.execute(f'SELECT COUNT(*) FROM "{t}"')
        count = cur.fetchone()[0]
        newest = ""
        for date_col in ("date", "invoice_date", "created_time", "expense_date"):
            try:
                cur.execute(f'SELECT MAX("{date_col}") FROM "{t}"')
                val = cur.fetchone()[0]
                if val is not None:
                    newest = f"  (newest {date_col}: {val})"
                    break
            except Exception:
                conn.rollback()
        print(f"  {t}: {count} rows{newest}")
    conn.close()
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")
    sys.exit(1)
