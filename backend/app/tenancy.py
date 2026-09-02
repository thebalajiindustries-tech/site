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
            """
        )


def create_tenant(name: str, db_url: str, location: str = "") -> int:
    with _cx() as c:
        cur = c.execute(
            "INSERT INTO tenants(name,location,db_url,created_at) VALUES(?,?,?,?)",
            (name, location, db_url, time.time()),
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
