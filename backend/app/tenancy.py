"""Control plane: which companies (tenants) exist and which users belong to them.

This is deliberately SEPARATE from tenant data. It is a small SQLite database of
companies + user logins. A tenant's financial data lives in that tenant's OWN
database (Postgres or SQLite), reached only through its stored db_url.
"""
import sqlite3
import time
from contextlib import contextmanager

from .config import get_settings

settings = get_settings()


@contextmanager
def _cx():
    conn = sqlite3.connect(settings.CONTROL_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with _cx() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS tenants (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL,
                location   TEXT DEFAULT '',
                db_url     TEXT NOT NULL,
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
            """
        )
        # migration: add wallet column to older control DBs, and give existing
        # companies a starting balance so they can use the app.
        cols = [r[1] for r in c.execute("PRAGMA table_info(tenants)").fetchall()]
        if "balance_inr" not in cols:
            c.execute("ALTER TABLE tenants ADD COLUMN balance_inr REAL DEFAULT 0")
            c.execute("UPDATE tenants SET balance_inr = ?", (settings.SEED_BALANCE_INR,))


def create_tenant(name: str, db_url: str, location: str = "", balance_inr: float = 0.0) -> int:
    with _cx() as c:
        cur = c.execute(
            "INSERT INTO tenants(name,location,db_url,created_at,balance_inr) VALUES(?,?,?,?,?)",
            (name, location, db_url, time.time(), balance_inr),
        )
        return cur.lastrowid


def get_tenant(tenant_id: int):
    with _cx() as c:
        r = c.execute("SELECT * FROM tenants WHERE id=?", (tenant_id,)).fetchone()
        return dict(r) if r else None


def get_tenant_by_name(name: str):
    with _cx() as c:
        r = c.execute("SELECT * FROM tenants WHERE name=? COLLATE NOCASE", (name,)).fetchone()
        return dict(r) if r else None


def create_user(email: str, pw_hash: str, tenant_id: int, role: str = "owner") -> int:
    with _cx() as c:
        cur = c.execute(
            "INSERT INTO users(email,pw_hash,tenant_id,role,created_at) VALUES(?,?,?,?,?)",
            (email.strip().lower(), pw_hash, tenant_id, role, time.time()),
        )
        return cur.lastrowid


def get_user_by_email(email: str):
    with _cx() as c:
        r = c.execute(
            "SELECT * FROM users WHERE email=? COLLATE NOCASE", (email.strip().lower(),)
        ).fetchone()
        return dict(r) if r else None


def get_user(user_id: int):
    with _cx() as c:
        r = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(r) if r else None


def count_users() -> int:
    with _cx() as c:
        return c.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]


def get_balance(tenant_id: int) -> float:
    with _cx() as c:
        r = c.execute("SELECT balance_inr FROM tenants WHERE id=?", (tenant_id,)).fetchone()
        return float(r["balance_inr"] or 0) if r else 0.0


def adjust_balance(tenant_id: int, delta_inr: float) -> float:
    """Atomically add delta (negative to debit). Returns the new balance."""
    with _cx() as c:
        c.execute("UPDATE tenants SET balance_inr = COALESCE(balance_inr,0) + ? WHERE id=?",
                  (delta_inr, tenant_id))
        r = c.execute("SELECT balance_inr FROM tenants WHERE id=?", (tenant_id,)).fetchone()
        return float(r["balance_inr"] or 0) if r else 0.0


def record_ledger(tenant_id: int, kind: str, amount_inr: float, balance_after: float, detail: str = "") -> None:
    with _cx() as c:
        c.execute(
            "INSERT INTO usage_ledger(tenant_id,ts,kind,amount_inr,balance_after,detail) VALUES(?,?,?,?,?,?)",
            (tenant_id, time.time(), kind, amount_inr, balance_after, detail),
        )


def recent_ledger(tenant_id: int, limit: int = 25) -> list:
    with _cx() as c:
        rows = c.execute(
            "SELECT ts,kind,amount_inr,balance_after,detail FROM usage_ledger "
            "WHERE tenant_id=? ORDER BY id DESC LIMIT ?", (tenant_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]