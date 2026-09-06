"""One-time bootstrap: create the control DB and two demo companies so the
multi-tenant setup is usable (and its isolation demonstrable) out of the box.

Local mode (no SUPABASE_DB_URL / CONTROL_DB_URL set):
  - The Balaji Industries  -> the real Zoho->Postgres warehouse (settings.DATABASE_URL)
  - Demo Traders           -> a self-contained SQLite warehouse with sample data
  - self-serve signups     -> a fresh empty SQLite warehouse per company

Cloud mode (CONTROL_DB_URL set, typically = SUPABASE_DB_URL):
  - every tenant (Balaji, Demo Traders, self-serve signups) is a separate
    Postgres SCHEMA inside that one shared Supabase database.
"""
import os
import re
import sqlite3
import logging

import psycopg2

from .config import get_settings
from . import tenancy, auth

log = logging.getLogger("ganak.seed")
settings = get_settings()

DEMO_USER = "demo@ganak.local"
DEMO_PASS = "demo123"
BALAJI_USER = "balaji@ganak.local"
BALAJI_PASS = "balaji123"


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_") or "tenant"
    if s[0].isdigit():
        s = "t_" + s
    return s


def cloud_mode() -> bool:
    return bool(settings.CONTROL_DB_URL)


def ensure_sqlite_warehouse(path: str, with_sample: bool = False):
    """Create the standard tables in a SQLite warehouse; optionally seed sample rows."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS invoices (
                invoice_number TEXT, customer_name TEXT, invoice_date TEXT,
                total REAL, status TEXT
            );
            CREATE TABLE IF NOT EXISTS payments (
                payment_number TEXT, customer_name TEXT, date TEXT,
                amount REAL, mode TEXT
            );
            CREATE TABLE IF NOT EXISTS expenses (
                expense_date TEXT, category TEXT, amount REAL, vendor TEXT
            );
            """
        )
        if with_sample and conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 0:
            _insert_sample(conn, "?")
        conn.commit()
    finally:
        conn.close()


def _insert_sample(conn_or_cur, ph: str):
    conn_or_cur.executemany(
        f"INSERT INTO payments(payment_number,customer_name,date,amount,mode) VALUES({','.join([ph]*5)})",
        [
            ("PMT-001", "Sunrise Apartments", "2026-04-12", 145000, "bank_transfer"),
            ("PMT-002", "Green Valley Society", "2026-05-03", 98000, "upi"),
            ("PMT-003", "Metro Mall",           "2026-05-27", 210000, "cheque"),
            ("PMT-004", "Sunrise Apartments",   "2026-06-18", 76000,  "upi"),
            ("PMT-005", "City Hospital",        "2026-07-09", 320000, "bank_transfer"),
            ("PMT-006", "Green Valley Society", "2026-08-14", 54000,  "upi"),
            ("PMT-007", "Metro Mall",           "2026-08-30", 129000, "cheque"),
        ],
    )
    conn_or_cur.executemany(
        f"INSERT INTO invoices(invoice_number,customer_name,invoice_date,total,status) VALUES({','.join([ph]*5)})",
        [
            ("INV-101", "Sunrise Apartments",   "2026-04-01", 145000, "paid"),
            ("INV-102", "Green Valley Society", "2026-05-01", 98000,  "paid"),
            ("INV-103", "Metro Mall",           "2026-05-20", 210000, "paid"),
            ("INV-104", "City Hospital",        "2026-07-01", 320000, "paid"),
            ("INV-105", "Riverside Homes",      "2026-08-05", 187000, "unpaid"),
            ("INV-106", "Metro Mall",           "2026-08-25", 129000, "unpaid"),
        ],
    )
    conn_or_cur.executemany(
        f"INSERT INTO expenses(expense_date,category,amount,vendor) VALUES({','.join([ph]*4)})",
        [
            ("2026-04-10", "Equipment", 62000, "CP Plus"),
            ("2026-05-15", "Labour",    38000, "Onsite Team"),
            ("2026-06-20", "Transport", 12000, "VRL Logistics"),
            ("2026-07-22", "Equipment", 88000, "Hikvision"),
        ],
    )


def ensure_pg_warehouse(db_url: str, schema: str, with_sample: bool = False):
    """Create the standard tables in a Postgres SCHEMA within db_url; optionally seed sample rows."""
    conn = psycopg2.connect(db_url, connect_timeout=10)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}";')
            cur.execute(f'SET search_path TO "{schema}";')
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS invoices (
                    invoice_number TEXT, customer_name TEXT, invoice_date DATE,
                    total NUMERIC, status TEXT
                );
                CREATE TABLE IF NOT EXISTS payments (
                    payment_number TEXT, customer_name TEXT, date DATE,
                    amount NUMERIC, mode TEXT
                );
                CREATE TABLE IF NOT EXISTS expenses (
                    expense_date DATE, category TEXT, amount NUMERIC, vendor TEXT
                );
                """
            )
            if with_sample:
                cur.execute("SELECT COUNT(*) FROM payments;")
                if cur.fetchone()[0] == 0:
                    _insert_sample(cur, "%s")
    finally:
        conn.close()


def provision_tenant_db(company_name: str) -> tuple[str, str]:
    """Create a fresh, empty warehouse for a newly signed-up company.
    Returns (db_url, db_schema) — db_schema is '' for local SQLite tenants.
    """
    if cloud_mode():
        base = _slug(company_name)
        schema = base
        i = 1
        existing = {t["db_schema"] for t in _all_schema_names()}
        while schema in existing:
            schema = f"{base}_{i}"
            i += 1
        ensure_pg_warehouse(settings.SUPABASE_DB_URL, schema, with_sample=False)
        return settings.SUPABASE_DB_URL, schema

    fname = _slug(company_name) + ".db"
    path = os.path.join(settings.TENANTS_DIR, fname)
    i = 1
    while os.path.exists(path):
        path = os.path.join(settings.TENANTS_DIR, f"{_slug(company_name)}_{i}.db")
        i += 1
    ensure_sqlite_warehouse(path, with_sample=False)
    return "sqlite:///" + path, ""


def _all_schema_names():
    # best-effort de-dup helper; a fresh control DB just returns nothing
    try:
        with tenancy._cx() as conn:  # noqa: SLF001 (internal helper, same package)
            cur = tenancy._cur(conn)
            cur.execute("SELECT db_schema FROM tenants")
            return [dict(r) for r in cur.fetchall()]
    except Exception:
        return []


def bootstrap():
    tenancy.init_db()
    if not settings.SEED_DEMO or tenancy.count_users() > 0:
        return

    if cloud_mode():
        # everyone lives in the shared Supabase project, one schema each
        balaji_url = settings.SUPABASE_DB_URL
        ensure_pg_warehouse(balaji_url, "balaji", with_sample=False)
        balaji_tid = tenancy.create_tenant(
            "The Balaji Industries", balaji_url, "Kharadi, Pune", settings.SEED_BALANCE_INR, "balaji"
        )
        tenancy.create_user(BALAJI_USER, auth.hash_password(BALAJI_PASS), balaji_tid, "owner")

        ensure_pg_warehouse(balaji_url, "demo_traders", with_sample=True)
        demo_tid = tenancy.create_tenant(
            "Demo Traders", balaji_url, "Pune", settings.SEED_BALANCE_INR, "demo_traders"
        )
        tenancy.create_user(DEMO_USER, auth.hash_password(DEMO_PASS), demo_tid, "owner")
        log.info("Seeded demo companies on Supabase: schemas 'balaji' and 'demo_traders'.")
        return

    # 1) The Balaji Industries -> real Postgres warehouse (local)
    balaji_tid = tenancy.create_tenant(
        "The Balaji Industries", settings.DATABASE_URL, "Kharadi, Pune", settings.SEED_BALANCE_INR
    )
    tenancy.create_user(BALAJI_USER, auth.hash_password(BALAJI_PASS), balaji_tid, "owner")

    # 2) Demo Traders -> self-contained SQLite warehouse with sample data
    ensure_sqlite_warehouse(settings.DEMO_DB_PATH, with_sample=True)
    demo_tid = tenancy.create_tenant(
        "Demo Traders", "sqlite:///" + settings.DEMO_DB_PATH, "Pune", settings.SEED_BALANCE_INR
    )
    tenancy.create_user(DEMO_USER, auth.hash_password(DEMO_PASS), demo_tid, "owner")

    log.info("Seeded demo companies: %s (Postgres) and Demo Traders (SQLite).",
             "The Balaji Industries")
