"""Database access — read-only connections against the warehouse."""
import psycopg2
import psycopg2.extras

from .config import get_settings

settings = get_settings()

# Cache the schema string in memory (it rarely changes; the sync job appends rows).
_schema_cache: str | None = None


def get_conn():
    """A strictly read-only connection with a statement timeout.

    Read-only + statement_timeout are the cheapest, strongest guardrails:
    the LLM can never write, and a runaway query can't hang the app.
    """
    # connect_timeout keeps a wrong password / stopped Postgres from hanging the
    # whole app — it fails fast so /health can report the database as down.
    conn = psycopg2.connect(settings.DATABASE_URL, connect_timeout=5)
    conn.set_session(readonly=True, autocommit=True)
    with conn.cursor() as cur:
        cur.execute(f"SET statement_timeout = {settings.STATEMENT_TIMEOUT_MS};")
    return conn


def load_schema(refresh: bool = False) -> str:
    """Return a compact text description of public tables + columns for the LLM prompt."""
    global _schema_cache
    if _schema_cache is not None and not refresh:
        return _schema_cache

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name NOT LIKE 'pg_%'
              AND table_name <> 'sync_metadata'
            ORDER BY table_name, ordinal_position;
            """
        )
        tables: dict[str, list[str]] = {}
        for table, col, dtype in cur.fetchall():
            tables.setdefault(table, []).append(f"{col} {dtype}")

    _schema_cache = "\n".join(
        f"TABLE {t} (" + ", ".join(cols) + ")" for t, cols in tables.items()
    )
    return _schema_cache


def run_select(sql: str):
    """Execute a (pre-sanitized) SELECT and return (columns, rows)."""
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql)
        rows = cur.fetchall()
    columns = list(rows[0].keys()) if rows else []
    return columns, [dict(r) for r in rows]


def ping() -> bool:
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1;")
            cur.fetchone()
        return True
    except Exception:
        return False
