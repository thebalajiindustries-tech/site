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
import psycopg2.pool

from .config import get_settings

settings = get_settings()

# schema text cache, keyed by (db_url, db_schema) — each tenant cached independently
_schema_cache: dict[tuple[str, str], str] = {}

# One small pooled-connection set per distinct Postgres db_url. In practice
# there's usually just one (the shared Supabase project all cloud tenants
# live in) reused across every tenant's own schema. Before this, every
# /ask, /schema, /health and dashboard call opened a brand-new TCP+TLS
# connection to Postgres -- pure avoidable latency on every request. A
# pooled connection is checked out, re-pointed at the caller's schema (see
# _pg_conn), used, and returned -- never closed on the happy path.
_pools: dict[str, "psycopg2.pool.ThreadedConnectionPool"] = {}


def _get_pool(db_url: str) -> "psycopg2.pool.ThreadedConnectionPool":
    pool = _pools.get(db_url)
    if pool is None:
        pool = psycopg2.pool.ThreadedConnectionPool(
            settings.PG_POOL_MINCONN, settings.PG_POOL_MAXCONN, db_url, connect_timeout=5,
        )
        _pools[db_url] = pool
    return pool


def dialect_of(db_url: str) -> str:
    return "sqlite" if db_url.startswith("sqlite") else "postgres"


def _sqlite_path(db_url: str) -> str:
    return db_url.replace("sqlite:///", "", 1)


def _key(db_url: str, schema: str | None) -> tuple[str, str]:
    return (db_url, schema or "")


# ---------- connections ----------
def _pg_conn(db_url: str, schema: str | None = None):
    """Check a pooled connection out and (re)point it at this tenant's schema.
    readonly/autocommit/statement_timeout/search_path are re-applied on every
    checkout, so a connection last used by a different tenant is always left
    correctly scoped before the caller sees it."""
    conn = _get_pool(db_url).getconn()
    conn.set_session(readonly=True, autocommit=True)
    with conn.cursor() as cur:
        cur.execute(f"SET statement_timeout = {settings.STATEMENT_TIMEOUT_MS};")
        cur.execute(f'SET search_path TO "{schema or "public"}", public;')
    return conn


def _pg_release(db_url: str, conn, ok: bool = True) -> None:
    """Return a connection to its pool, or discard it (ok=False) when it might
    be left in a bad state after an error -- so one broken connection can't
    poison the pool for every other tenant sharing this db_url."""
    try:
        _get_pool(db_url).putconn(conn, close=not ok)
    except Exception:
        pass


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
    ok = False
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
        ok = True
    finally:
        _pg_release(db_url, conn, ok)
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
        ok = False
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(sql)
            rows = [dict(r) for r in cur.fetchall()]
            ok = True
        finally:
            _pg_release(db_url, conn, ok)
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
            ok = False
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1;")
                    cur.fetchone()
                ok = True
            finally:
                _pg_release(db_url, conn, ok)
        return True
    except Exception:
        return False


def invalidate_schema(db_url: str | None = None, schema: str | None = None) -> None:
    """Drop the cached schema so a newly created table (e.g. `documents`) is seen."""
    if db_url is None:
        _schema_cache.clear()
    else:
        _schema_cache.pop(_key(db_url, schema), None)
