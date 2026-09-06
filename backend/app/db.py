"""Tenant-aware, strictly READ-ONLY data access.

Each tenant has its own database (db_url) OR, for tenants sharing the Supabase
Postgres project, its own SCHEMA within that one database (db_url + db_schema).
Either way we only ever open a read-only connection scoped to that tenant, so
the AI can never write and can never reach another tenant's data.

Engines supported:
  - postgresql://…   psycopg2, session set READ ONLY + statement timeout
                      (+ search_path pinned to the tenant's schema, when given)
  - sqlite:///path    opened with PRAGMA query_only = ON
"""
import sqlite3

import psycopg2
import psycopg2.extras

from .config import get_settings

settings = get_settings()

# schema text cache, keyed by (db_url, db_schema) — each tenant cached independently
_schema_cache: dict[tuple[str, str], str] = {}


def dialect_of(db_url: str) -> str:
    return "sqlite" if db_url.startswith("sqlite") else "postgres"


def _sqlite_path(db_url: str) -> str:
    return db_url.replace("sqlite:///", "", 1)


def _key(db_url: str, schema: str | None) -> tuple[str, str]:
    return (db_url, schema or "")


# ---------- connections ----------
def _pg_conn(db_url: str, schema: str | None = None):
    conn = psycopg2.connect(db_url, connect_timeout=5)
    conn.set_session(readonly=True, autocommit=True)
    with conn.cursor() as cur:
        cur.execute(f"SET statement_timeout = {settings.STATEMENT_TIMEOUT_MS};")
        if schema:
            # quoted identifier — schema names come from our own tenant records,
            # never from user input, but quote defensively anyway.
            cur.execute(f'SET search_path TO "{schema}", public;')
    return conn


def _sqlite_conn(db_url: str):
    conn = sqlite3.connect(_sqlite_path(db_url), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON;")  # hard read-only
    return conn


# ---------- schema ----------
def load_schema(db_url: str, schema: str | None = None, refresh: bool = False) -> str:
    key = _key(db_url, schema)
    if not refresh and key in _schema_cache:
        return _schema_cache[key]
    out = (
        _load_schema_sqlite(db_url)
        if dialect_of(db_url) == "sqlite"
        else _load_schema_pg(db_url, schema)
    )
    _schema_cache[key] = out
    return out


def _load_schema_pg(db_url: str, schema: str | None = None) -> str:
    conn = _pg_conn(db_url, schema)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name NOT LIKE 'pg_%%'
                  AND table_name <> 'sync_metadata'
                ORDER BY table_name, ordinal_position;
                """,
                (schema or "public",),
            )
            tables: dict[str, list[str]] = {}
            for t, col, dtype in cur.fetchall():
                tables.setdefault(t, []).append(f"{col} {dtype}")
    finally:
        conn.close()
    return "\n".join(f"TABLE {t} (" + ", ".join(c) + ")" for t, c in tables.items())


def _load_schema_sqlite(db_url: str) -> str:
    conn = _sqlite_conn(db_url)
    try:
        names = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        out = []
        for t in names:
            cols = conn.execute(f'PRAGMA table_info("{t}")').fetchall()
            desc = ", ".join(f"{c['name']} {c['type'] or 'TEXT'}" for c in cols)
            out.append(f"TABLE {t} ({desc})")
    finally:
        conn.close()
    return "\n".join(out)


# ---------- queries ----------
def run_select(db_url: str, sql: str, schema: str | None = None):
    """Execute a pre-sanitized SELECT against the tenant DB. Returns (columns, rows)."""
    if dialect_of(db_url) == "sqlite":
        conn = _sqlite_conn(db_url)
        try:
            rows = [dict(r) for r in conn.execute(sql).fetchall()]
        finally:
            conn.close()
    else:
        conn = _pg_conn(db_url, schema)
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(sql)
            rows = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
    columns = list(rows[0].keys()) if rows else []
    return columns, rows


def ping(db_url: str, schema: str | None = None) -> bool:
    try:
        if dialect_of(db_url) == "sqlite":
            conn = _sqlite_conn(db_url)
            conn.execute("SELECT 1;").fetchone()
            conn.close()
        else:
            conn = _pg_conn(db_url, schema)
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                cur.fetchone()
            conn.close()
        return True
    except Exception:
        return False


def invalidate_schema(db_url: str | None = None, schema: str | None = None) -> None:
    """Drop the cached schema so a newly created table (e.g. `documents`) is seen."""
    if db_url is None:
        _schema_cache.clear()
    else:
        _schema_cache.pop(_key(db_url, schema), None)
