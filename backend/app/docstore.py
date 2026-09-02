"""Writable store for AI-extracted documents.

This is the only place the app writes tenant data, and it writes ONLY to the
`documents` table via fixed, parameterized SQL. The AI never writes — it extracts
fields a human confirms, and this inserts them. Works on Postgres or SQLite.
"""
import json
import sqlite3
import datetime

import psycopg2

from .config import get_settings
from .db import dialect_of, _sqlite_path

settings = get_settings()


def _now():
    return datetime.datetime.utcnow().isoformat(timespec="seconds")


def ensure_table(db_url: str) -> None:
    if dialect_of(db_url) == "sqlite":
        c = sqlite3.connect(_sqlite_path(db_url), timeout=5)
        c.execute(
            """CREATE TABLE IF NOT EXISTS documents(
                id INTEGER PRIMARY KEY AUTOINCREMENT, doc_type TEXT, party TEXT,
                doc_date TEXT, amount REAL, currency TEXT, reference_no TEXT,
                gst_no TEXT, direction TEXT, summary TEXT, source_filename TEXT,
                uploaded_at TEXT, raw_json TEXT)"""
        )
        c.commit(); c.close()
    else:
        c = psycopg2.connect(db_url, connect_timeout=5); c.autocommit = True
        cur = c.cursor()
        cur.execute(
            """CREATE TABLE IF NOT EXISTS documents(
                id SERIAL PRIMARY KEY, doc_type TEXT, party TEXT, doc_date DATE,
                amount NUMERIC, currency TEXT, reference_no TEXT, gst_no TEXT,
                direction TEXT, summary TEXT, source_filename TEXT,
                uploaded_at TIMESTAMP, raw_json TEXT)"""
        )
        c.close()


def _clean(rec: dict) -> tuple:
    def g(k):
        v = rec.get(k)
        return v if v not in ("", None) else None
    amt = g("amount")
    try:
        amt = float(amt) if amt is not None else None
    except (TypeError, ValueError):
        amt = None
    return (
        g("doc_type"), g("party"), g("doc_date"), amt, rec.get("currency") or "INR",
        g("reference_no"), g("gst_no"), g("direction"), g("summary"),
        g("source_filename"), _now(), json.dumps(rec.get("raw") or {}, default=str),
    )


_COLS = ("doc_type,party,doc_date,amount,currency,reference_no,gst_no,"
         "direction,summary,source_filename,uploaded_at,raw_json")


def insert_document(db_url: str, rec: dict) -> None:
    ensure_table(db_url)
    vals = _clean(rec)
    if dialect_of(db_url) == "sqlite":
        c = sqlite3.connect(_sqlite_path(db_url), timeout=5)
        c.execute(f"INSERT INTO documents({_COLS}) VALUES({','.join(['?']*12)})", vals)
        c.commit(); c.close()
    else:
        c = psycopg2.connect(db_url, connect_timeout=5); c.autocommit = True
        cur = c.cursor()
        cur.execute(f"INSERT INTO documents({_COLS}) VALUES({','.join(['%s']*12)})", vals)
        c.close()
