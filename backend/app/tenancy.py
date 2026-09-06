"""Control plane: which companies (tenants) exist and which users belong to them.

This is deliberately SEPARATE from tenant data. It runs on SQLite by default
(local dev / tests) or on Postgres — settings.CONTROL_DB_URL, typically the
shared Supabase project — in production. Either way a tenant's financial data
lives in that tenant's OWN database/schema, reached only through its stored
db_url (+ db_schema for a Postgres tenant sharing the Supabase project).
"""
import sqlite3
import time
from contextlib import contextmanager

import psycopg2
import psycopg2.extras

from .config import get_settings

settings = get_settings()


def _control_url() -> str:
    return settings.CONTROL_DB_URL or f"sqlite:///{settings.CONTROL_DB_PATH}"


def _dialect() -> str:
    return "sqlite" if _control_url().startswith("sqlite") else "postgres"


@contextmanager
def _cx():
    url = _control_url()
    if _dialect() == "sqlite":
        conn = sqlite3.connect(url.replace("sqlite:///", "", 1))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
    else:
        conn = psycopg2.connect(url, connect_timeout=10)
        with conn.cursor() as c:
            c.execute("CREATE SCHEMA IF NOT EXISTS control;")
            c.execute("SET search_path TO control;")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def _cur(conn):
    """A cursor that yields dict-like rows on either engine."""
    if _dialect() == "postgres":
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    return conn.cursor()


def _q(sql: str) -> str:
    """Adapt a `?`-placeholder query to the active engine's paramstyle."""
    return sql.replace("?", "%s") if _dialect() == "postgres" else sql


def _row(r):
    return dict(r) if r is not None else None


def init_db():
    pg = _dialect() == "postgres"
    with _cx() as conn:
        cur = conn.cursor()
        if pg:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS tenants (
                    id          SERIAL PRIMARY KEY,
                    name        TEXT NOT NULL,
                    location    TEXT DEFAULT '',
                    db_url      TEXT NOT NULL,
                    db_schema   TEXT DEFAULT '',
                    balance_inr REAL DEFAULT 0,
                    created_at  DOUBLE PRECISION NOT NULL
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id         SERIAL PRIMARY KEY,
                    email      TEXT NOT NULL UNIQUE,
                    pw_hash    TEXT NOT NULL,
                    tenant_id  INTEGER NOT NULL REFERENCES tenants(id),
                    role       TEXT DEFAULT 'owner',
                    created_at DOUBLE PRECISION NOT NULL
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_ledger (
                    id            SERIAL PRIMARY KEY,
                    tenant_id     INTEGER NOT NULL,
                    ts            DOUBLE PRECISION NOT NULL,
                    kind          TEXT NOT NULL,
                    amount_inr    REAL NOT NULL,
                    balance_after REAL,
                    detail        TEXT DEFAULT ''
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS connectors (
                    id                SERIAL PRIMARY KEY,
                    tenant_id         INTEGER NOT NULL REFERENCES tenants(id),
                    provider          TEXT NOT NULL,
                    status            TEXT NOT NULL DEFAULT 'connected',
                    account_label     TEXT DEFAULT '',
                    org_id            TEXT DEFAULT '',
                    refresh_token_enc TEXT NOT NULL DEFAULT '',
                    access_token_enc  TEXT DEFAULT '',
                    token_expires_at  DOUBLE PRECISION DEFAULT 0,
                    scopes            TEXT DEFAULT '',
                    last_synced_at    DOUBLE PRECISION DEFAULT 0,
                    last_error        TEXT DEFAULT '',
                    created_at        DOUBLE PRECISION NOT NULL,
                    UNIQUE(tenant_id, provider)
                );
                """
            )
        else:
            cur.executescript(
                """
                CREATE TABLE IF NOT EXISTS tenants (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    name       TEXT NOT NULL,
                    location   TEXT DEFAULT '',
                    db_url     TEXT NOT NULL,
                    db_schema  TEXT DEFAULT '',
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS users (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    email      TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    pw_hash    TEXT NOT NULL,
                    tenant_id  INTEGER NOT NULL,
                    role       TEXT DEFAULT 'owner',
                    created_at REAL NOT NULL,
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id)
                );
                CREATE TABLE IF NOT EXISTS usage_ledger (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id     INTEGER NOT NULL,
                    ts            REAL NOT NULL,
                    kind          TEXT NOT NULL,
                    amount_inr    REAL NOT NULL,
                    balance_after REAL,
                    detail        TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS connectors (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id         INTEGER NOT NULL,
                    provider          TEXT NOT NULL,
                    status            TEXT NOT NULL DEFAULT 'connected',
                    account_label     TEXT DEFAULT '',
                    org_id            TEXT DEFAULT '',
                    refresh_token_enc TEXT NOT NULL DEFAULT '',
                    access_token_enc  TEXT DEFAULT '',
                    token_expires_at  REAL DEFAULT 0,
                    scopes            TEXT DEFAULT '',
                    last_synced_at    REAL DEFAULT 0,
                    last_error        TEXT DEFAULT '',
                    created_at        REAL NOT NULL,
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id),
                    UNIQUE(tenant_id, provider)
                );
                """
            )
            # migrations for older local control DBs
            cols = [r[1] for r in cur.execute("PRAGMA table_info(tenants)").fetchall()]
            if "balance_inr" not in cols:
                cur.execute("ALTER TABLE tenants ADD COLUMN balance_inr REAL DEFAULT 0")
                cur.execute("UPDATE tenants SET balance_inr = ?", (settings.SEED_BALANCE_INR,))
            if "db_schema" not in cols:
                cur.execute("ALTER TABLE tenants ADD COLUMN db_schema TEXT DEFAULT ''")


def create_tenant(name: str, db_url: str, location: str = "", balance_inr: float = 0.0,
                   db_schema: str = "") -> int:
    with _cx() as conn:
        cur = conn.cursor()
        if _dialect() == "postgres":
            cur.execute(
                _q("INSERT INTO tenants(name,location,db_url,db_schema,created_at,balance_inr) "
                   "VALUES(?,?,?,?,?,?) RETURNING id"),
                (name, location, db_url, db_schema, time.time(), balance_inr),
            )
            return cur.fetchone()[0]
        cur.execute(
            "INSERT INTO tenants(name,location,db_url,db_schema,created_at,balance_inr) VALUES(?,?,?,?,?,?)",
            (name, location, db_url, db_schema, time.time(), balance_inr),
        )
        return cur.lastrowid


def get_tenant(tenant_id: int):
    with _cx() as conn:
        cur = _cur(conn)
        cur.execute(_q("SELECT * FROM tenants WHERE id=?"), (tenant_id,))
        return _row(cur.fetchone())


def get_tenant_by_name(name: str):
    with _cx() as conn:
        cur = _cur(conn)
        cur.execute(_q("SELECT * FROM tenants WHERE LOWER(name)=LOWER(?)"), (name,))
        return _row(cur.fetchone())


def create_user(email: str, pw_hash: str, tenant_id: int, role: str = "owner") -> int:
    email = email.strip().lower()
    with _cx() as conn:
        cur = conn.cursor()
        if _dialect() == "postgres":
            cur.execute(
                _q("INSERT INTO users(email,pw_hash,tenant_id,role,created_at) "
                   "VALUES(?,?,?,?,?) RETURNING id"),
                (email, pw_hash, tenant_id, role, time.time()),
            )
            return cur.fetchone()[0]
        cur.execute(
            "INSERT INTO users(email,pw_hash,tenant_id,role,created_at) VALUES(?,?,?,?,?)",
            (email, pw_hash, tenant_id, role, time.time()),
        )
        return cur.lastrowid


def get_user_by_email(email: str):
    with _cx() as conn:
        cur = _cur(conn)
        cur.execute(_q("SELECT * FROM users WHERE LOWER(email)=LOWER(?)"), (email.strip().lower(),))
        return _row(cur.fetchone())


def get_user(user_id: int):
    with _cx() as conn:
        cur = _cur(conn)
        cur.execute(_q("SELECT * FROM users WHERE id=?"), (user_id,))
        return _row(cur.fetchone())


def count_users() -> int:
    with _cx() as conn:
        cur = _cur(conn)
        cur.execute("SELECT COUNT(*) AS n FROM users")
        r = cur.fetchone()
        return int(r["n"])


def get_balance(tenant_id: int) -> float:
    with _cx() as conn:
        cur = _cur(conn)
        cur.execute(_q("SELECT balance_inr FROM tenants WHERE id=?"), (tenant_id,))
        r = cur.fetchone()
        return float(r["balance_inr"] or 0) if r else 0.0


def adjust_balance(tenant_id: int, delta_inr: float) -> float:
    """Atomically add delta (negative to debit). Returns the new balance."""
    with _cx() as conn:
        cur = conn.cursor()
        cur.execute(_q("UPDATE tenants SET balance_inr = COALESCE(balance_inr,0) + ? WHERE id=?"),
                    (delta_inr, tenant_id))
        cur2 = _cur(conn)
        cur2.execute(_q("SELECT balance_inr FROM tenants WHERE id=?"), (tenant_id,))
        r = cur2.fetchone()
        return float(r["balance_inr"] or 0) if r else 0.0


def record_ledger(tenant_id: int, kind: str, amount_inr: float, balance_after: float, detail: str = "") -> None:
    with _cx() as conn:
        cur = conn.cursor()
        cur.execute(
            _q("INSERT INTO usage_ledger(tenant_id,ts,kind,amount_inr,balance_after,detail) VALUES(?,?,?,?,?,?)"),
            (tenant_id, time.time(), kind, amount_inr, balance_after, detail),
        )


def recent_ledger(tenant_id: int, limit: int = 25) -> list:
    with _cx() as conn:
        cur = _cur(conn)
        cur.execute(
            _q("SELECT ts,kind,amount_inr,balance_after,detail FROM usage_ledger "
               "WHERE tenant_id=? ORDER BY id DESC LIMIT ?"),
            (tenant_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]


# ---------------- self-serve connectors (Gmail, Zoho, ...) ----------------
# One row per (tenant, provider): re-connecting overwrites the old tokens
# rather than creating a duplicate. Tokens are stored already-encrypted
# (see app/crypto.py) -- this module never sees plaintext tokens.

def upsert_connector(tenant_id: int, provider: str, refresh_token_enc: str,
                      access_token_enc: str = "", token_expires_at: float = 0.0,
                      org_id: str = "", account_label: str = "", scopes: str = "") -> int:
    with _cx() as conn:
        cur = conn.cursor()
        if _dialect() == "postgres":
            cur.execute(
                _q("""
                INSERT INTO connectors(tenant_id, provider, status, account_label, org_id,
                                        refresh_token_enc, access_token_enc, token_expires_at,
                                        scopes, created_at, last_error)
                VALUES(?,?,?,?,?,?,?,?,?,?,'')
                ON CONFLICT (tenant_id, provider) DO UPDATE SET
                    status = 'connected', account_label = EXCLUDED.account_label,
                    org_id = EXCLUDED.org_id, refresh_token_enc = EXCLUDED.refresh_token_enc,
                    access_token_enc = EXCLUDED.access_token_enc,
                    token_expires_at = EXCLUDED.token_expires_at, scopes = EXCLUDED.scopes,
                    last_error = ''
                RETURNING id
                """),
                (tenant_id, provider, "connected", account_label, org_id,
                 refresh_token_enc, access_token_enc, token_expires_at, scopes, time.time()),
            )
            return cur.fetchone()[0]
        cur.execute("SELECT id FROM connectors WHERE tenant_id=? AND provider=?", (tenant_id, provider))
        row = cur.fetchone()
        if row:
            cur.execute(
                "UPDATE connectors SET status='connected', account_label=?, org_id=?, "
                "refresh_token_enc=?, access_token_enc=?, token_expires_at=?, scopes=?, last_error='' "
                "WHERE id=?",
                (account_label, org_id, refresh_token_enc, access_token_enc, token_expires_at, scopes, row["id"]),
            )
            return row["id"]
        cur.execute(
            "INSERT INTO connectors(tenant_id, provider, status, account_label, org_id, "
            "refresh_token_enc, access_token_enc, token_expires_at, scopes, created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (tenant_id, provider, "connected", account_label, org_id,
             refresh_token_enc, access_token_enc, token_expires_at, scopes, time.time()),
        )
        return cur.lastrowid


def get_connector(tenant_id: int, provider: str):
    with _cx() as conn:
        cur = _cur(conn)
        cur.execute(_q("SELECT * FROM connectors WHERE tenant_id=? AND provider=?"), (tenant_id, provider))
        return _row(cur.fetchone())


def list_connectors(tenant_id: int) -> list:
    with _cx() as conn:
        cur = _cur(conn)
        cur.execute(_q("SELECT * FROM connectors WHERE tenant_id=? ORDER BY provider"), (tenant_id,))
        return [dict(r) for r in cur.fetchall()]


def update_connector_access_token(connector_id: int, access_token_enc: str, token_expires_at: float) -> None:
    with _cx() as conn:
        cur = conn.cursor()
        cur.execute(
            _q("UPDATE connectors SET access_token_enc=?, token_expires_at=? WHERE id=?"),
            (access_token_enc, token_expires_at, connector_id),
        )


def mark_connector_synced(connector_id: int) -> None:
    with _cx() as conn:
        cur = conn.cursor()
        cur.execute(
            _q("UPDATE connectors SET last_synced_at=?, status='connected', last_error='' WHERE id=?"),
            (time.time(), connector_id),
        )


def mark_connector_error(connector_id: int, error: str) -> None:
    with _cx() as conn:
        cur = conn.cursor()
        cur.execute(
            _q("UPDATE connectors SET status='error', last_error=? WHERE id=?"),
            (error[:500], connector_id),
        )


def delete_connector(tenant_id: int, provider: str) -> None:
    with _cx() as conn:
        cur = conn.cursor()
        cur.execute(_q("DELETE FROM connectors WHERE tenant_id=? AND provider=?"), (tenant_id, provider))
