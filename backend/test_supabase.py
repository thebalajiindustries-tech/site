"""One-off check: can this machine reach the Supabase Postgres database?

Run this from the backend folder (same place as .env). It never prints the
full connection string or password -- only success/failure and a couple of
harmless diagnostics.
"""
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv(override=True)

url = os.environ.get("SUPABASE_DB_URL", "")

if not url:
    print("FAIL: SUPABASE_DB_URL is not set in backend/.env")
    sys.exit(1)

print(f"Found SUPABASE_DB_URL in .env (length={len(url)} chars). Testing connection...")

try:
    import psycopg2
except ImportError:
    print("psycopg2 not installed -- installing now...")
    os.system(f"{sys.executable} -m pip install --quiet psycopg2-binary")
    import psycopg2

try:
    t0 = time.time()
    conn = psycopg2.connect(url, connect_timeout=10)
    cur = conn.cursor()
    cur.execute("select version();")
    version = cur.fetchone()[0]
    elapsed = time.time() - t0
    cur.close()
    conn.close()
    print(f"SUCCESS: connected in {elapsed:.2f}s")
    print(f"Server says: {version[:60]}...")
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")
    sys.exit(1)
