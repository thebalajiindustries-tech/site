"""Inbox -> Books: find finance emails that are not in Zoho Books yet, and add
them -- but only when the user reviews and confirms each one.

Three steps, each its own endpoint (see inbox_books_routes.py):

  1. find_missing()  READ-ONLY. Compares the tenant's synced Gmail `emails`
                     table with their synced Zoho tables (bills, payments,
                     estimates, purchaseorders, salesorders, expenses) and
                     lists recent emails with no matching Zoho record. No AI
                     call, no wallet charge.
  2. extract()       Opens ONE email (full body + first PDF attachment) and
                     asks Claude for the fields Zoho needs. Charged to the
                     wallet like any other AI call. Nothing is written.
  3. create()        Writes ONE record to Zoho Books, only after the user has
                     reviewed the fields. Refused unless INBOX_BOOKS_WRITE=1,
                     never runs on its own, and refuses a second create for
                     the same email.

Ask (the chat box) stays strictly read-only; it only points people here.
"""
import base64
import json
import logging
import math
import re
import time
from contextlib import contextmanager
from datetime import datetime, timezone

import pandas as pd
import requests
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from .config import get_settings
from . import billing, connectors_gmail, connectors_zoho
from .email_classify import classify, parse_amount, parse_amounts, parse_dates

log = logging.getLogger("ganak.inbox_books")
settings = get_settings()

RECORD_TYPES = ("bill", "customer_payment", "vendor_payment", "estimate", "purchase_order", "sales_order", "expense")

# record type -> (synced Zoho table, amount cols, date cols, reference cols, Zoho API endpoint, response key)
_SPECS = {
    "bill": dict(table="bills", amount=("total", "bcy_total", "amount"), date=("date",),
                 refs=("bill_number", "reference_number"), endpoint="bills", key="bill", party="vendor"),
    "customer_payment": dict(table="payments", amount=("amount", "bcy_amount"), date=("date",),
                             refs=("payment_number", "reference_number"), endpoint="customerpayments",
                             key="payment", party="customer"),
    # a payment WE made to a supplier (Zoho: Purchases -> Payments Made)
    "vendor_payment": dict(table="vendor_payments", amount=("amount", "bcy_amount"), date=("date",),
                           refs=("payment_number", "reference_number"), endpoint="vendorpayments",
                           key="payment", party="vendor"),
    "estimate": dict(table="estimates", amount=("total",), date=("date",),
                     refs=("estimate_number", "reference_number"), endpoint="estimates",
                     key="estimate", party="customer"),
    "purchase_order": dict(table="purchaseorders", amount=("total",), date=("date",),
                           refs=("purchaseorder_number", "reference_number"), endpoint="purchaseorders",
                           key="purchaseorder", party="vendor"),
    "sales_order": dict(table="salesorders", amount=("total",), date=("date",),
                        refs=("salesorder_number", "reference_number"), endpoint="salesorders",
                        key="salesorder", party="customer"),
    "expense": dict(table="expenses", amount=("total", "amount"), date=("date",),
                    refs=("reference_number",), endpoint="expenses", key="expense", party="vendor"),
}

_AMOUNT_TOLERANCE = 0.5
_DATE_WINDOW_DAYS = 10
_EXPENSE_HINT = re.compile(r"receipt|paid|payment (?:of|to)|order confirmation|expense", re.IGNORECASE)
_PO_REMINDER = re.compile(r"\b(?:statement|reminder|pending po|pending purchase|delivery schedule|on[- ]time delivery)\b",
                          re.IGNORECASE)
_INTENT = re.compile(
    r"(?=[\s\S]*\b(?:gmail|e-?mails?|mails?|inbox)\b)"
    r"(?=[\s\S]*\b(?:zoho|books?)\b)"
    r"(?=[\s\S]*\b(?:add(?! up)|added|adding|create|enter|push|not (?:in|there))\b)",
    re.IGNORECASE,
)
# analytics-style questions ("how many emails are in Zoho...") must keep going to the SQL path
_QUESTION_START = re.compile(r"\s*(?:how|what|when|which|who|show|list|total|count|compare)\b", re.IGNORECASE)
_ACTION_HINT = re.compile(r"\b(?:add it|add this|add them|not added|if (?:this|it) (?:is )?not)\b", re.IGNORECASE)
_MSG_ID = re.compile(r"^[0-9A-Za-z_-]{4,64}$")
_ZOHO_ID = re.compile(r"^[0-9A-Za-z_-]{1,64}$")
_BODY_CAP = 25          # emails whose full text is read per "Check again" (free Gmail reads, no AI)
_BODY_BUDGET_SECONDS = 20
_BODY_TEXT_KEEP = 4000  # characters of each email's text kept for matching (tenant's own database)


class InboxError(Exception):
    """An error with an HTTP status and a message safe to show the user."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# ---------------- small helpers ----------------
def looks_like_inbox_request(question: str) -> bool:
    """True for chat questions like 'check my Gmail and add it to Zoho Books'."""
    q = question or ""
    if _QUESTION_START.match(q) and not _ACTION_HINT.search(q):
        return False
    return bool(_INTENT.search(q))


def _qt(schema, table: str) -> str:
    return f'"{schema}"."{table}"' if schema else f'"{table}"'


def _engine(tenant: dict):
    return connectors_zoho._engine_for_tenant(tenant)


@contextmanager
def _db(tenant: dict):
    """(engine, schema) for this tenant, disposed afterwards so pools don't pile up."""
    engine, schema = _engine(tenant)
    try:
        yield engine, schema
    finally:
        try:
            engine.dispose()
        except Exception:
            pass


def _email_exists(engine, schema, message_id: str) -> bool:
    """Only ids that really are in THIS tenant's synced emails may be extracted / created / dismissed."""
    if not _MSG_ID.match(message_id or ""):
        return False
    try:
        with engine.connect() as c:
            row = c.execute(text(f"SELECT 1 FROM {_qt(schema, 'emails')} WHERE message_id = :m"),
                            {"m": message_id}).fetchone()
        return row is not None
    except Exception:
        return False


def _check_email(engine, schema, message_id: str) -> None:
    if not _email_exists(engine, schema, message_id):
        raise InboxError(404, "That email isn't in your synced Gmail data - sync Gmail and try again.")


def _has_table(engine, schema, table: str) -> bool:
    try:
        return inspect(engine).has_table(table, schema=schema)
    except Exception:
        return False


def _frame(engine, schema, table: str):
    if not _has_table(engine, schema, table):
        return None
    try:
        with engine.connect() as c:
            return pd.read_sql(text(f"SELECT * FROM {_qt(schema, table)}"), c)
    except Exception as e:
        log.warning("inbox_books: could not read %s: %s", table, e)
        return None


def _first_col(df: pd.DataFrame, names):
    for n in names:
        if n in df.columns:
            return n
    return None


def _num(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _iso(v) -> str:
    try:
        t = pd.to_datetime(v, errors="coerce", utc=True)
        return "" if pd.isna(t) else t.strftime("%Y-%m-%d")
    except Exception:
        return ""


# ---------------- action log (dedupe + dismiss) ----------------
def _ensure_actions(engine, schema) -> None:
    with engine.begin() as c:
        c.execute(text(
            f"CREATE TABLE IF NOT EXISTS {_qt(schema, 'inbox_actions')} ("
            "message_id TEXT NOT NULL, record_type TEXT NOT NULL, status TEXT NOT NULL, "
            "zoho_id TEXT, zoho_ref TEXT, detail TEXT, created_at TEXT, "
            "PRIMARY KEY (message_id, record_type))"
        ))


def _actions(engine, schema) -> dict:
    """{(message_id, record_type): status}; a '' record_type row (dismiss) hides the email."""
    _ensure_actions(engine, schema)
    with engine.connect() as c:
        rows = c.execute(text(f"SELECT message_id, record_type, status FROM {_qt(schema, 'inbox_actions')}")).fetchall()
    return {(r[0], r[1]): r[2] for r in rows}


def _record_action(engine, schema, message_id, record_type, status, zoho_id="", zoho_ref="", detail="") -> None:
    _ensure_actions(engine, schema)
    with engine.begin() as c:
        c.execute(text(f"DELETE FROM {_qt(schema, 'inbox_actions')} WHERE message_id=:m AND record_type=:t"),
                  {"m": message_id, "t": record_type})
        c.execute(text(
            f"INSERT INTO {_qt(schema, 'inbox_actions')} "
            "(message_id, record_type, status, zoho_id, zoho_ref, detail, created_at) "
            "VALUES (:m, :t, :s, :zi, :zr, :d, :ts)"),
            {"m": message_id, "t": record_type, "s": status, "zi": str(zoho_id or ""),
             "zr": str(zoho_ref or ""), "d": (detail or "")[:500],
             "ts": datetime.now(timezone.utc).isoformat()})


def dismiss(tenant: dict, message_id: str) -> None:
    with _db(tenant) as (engine, schema):
        _check_email(engine, schema, message_id)
        _record_action(engine, schema, message_id, "", "dismissed")


# ---------------- what an email's full text tells us (free: Gmail read, no AI) ----------------
def _ensure_body_cache(engine, schema) -> None:
    with engine.begin() as c:
        c.execute(text(
            f"CREATE TABLE IF NOT EXISTS {_qt(schema, 'inbox_body_facts')} ("
            "message_id TEXT PRIMARY KEY, body TEXT, amounts TEXT, dates TEXT, fetched_at TEXT)"
        ))


def _load_body_facts(engine, schema, ids) -> dict:
    """{message_id: {"body": str, "amounts": [float], "dates": ["YYYY-MM-DD"]}} for emails read before."""
    if not ids:
        return {}
    try:
        _ensure_body_cache(engine, schema)
        with engine.connect() as c:
            rows = c.execute(text(f"SELECT message_id, body, amounts, dates FROM {_qt(schema, 'inbox_body_facts')}")).fetchall()
    except Exception as e:
        log.warning("inbox_books: body cache unreadable: %s", e)
        return {}
    want, out = set(ids), {}
    for mid, body, amounts, dates in rows:
        if mid in want:
            try:
                out[mid] = {"body": body or "", "amounts": json.loads(amounts or "[]"), "dates": json.loads(dates or "[]")}
            except ValueError:
                continue
    return out


def _store_body_facts(engine, schema, message_id: str, text_body: str) -> dict:
    body = re.sub(r"\s+", " ", text_body or "").strip()[:_BODY_TEXT_KEEP]
    facts = {"body": body, "amounts": parse_amounts(body, limit=8), "dates": parse_dates(body, limit=8)}
    _ensure_body_cache(engine, schema)
    with engine.begin() as c:
        c.execute(text(f"DELETE FROM {_qt(schema, 'inbox_body_facts')} WHERE message_id=:m"), {"m": message_id})
        c.execute(text(
            f"INSERT INTO {_qt(schema, 'inbox_body_facts')} (message_id, body, amounts, dates, fetched_at) "
            "VALUES (:m, :b, :a, :d, :ts)"),
            {"m": message_id, "b": body, "a": json.dumps(facts["amounts"]), "d": json.dumps(facts["dates"]),
             "ts": datetime.now(timezone.utc).isoformat()})
    return facts


# ---------------- 1. find what is missing (read-only) ----------------
_WE_PAID_BY_DEBIT = re.compile(r"\bdebited\b", re.IGNORECASE)
_WE_PAID_THANKS = re.compile(r"thank you for your payment|received your payment|your payment (?:of .{0,30})?(?:has been|was) received",
                             re.IGNORECASE)
_RECEIVED_BY = re.compile(r"payment received by\s+(.+?)(?:\s+-\s+sent using|\s*$)", re.IGNORECASE)
_COMPANY_NOISE = re.compile(r"\b(?:the|pvt|private|ltd|limited|llp|and|co|company)\b")


def _company_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _COMPANY_NOISE.sub(" ", (name or "").lower()))


def _same_company(a: str, b: str) -> bool:
    ka, kb = _company_key(a), _company_key(b)
    return bool(ka) and bool(kb) and (ka in kb or kb in ka)


def payment_side(subject: str, text_blob: str, direction: str, company: str) -> str:
    """Who paid whom? 'in' = money came to us (a customer payment), 'out' = we paid a supplier
    (a vendor payment), '' = can't tell / nothing to book.

    The classic trap is a Zoho Books mail "Payment Received by <SUPPLIER> - Sent Using Zoho Books":
    the supplier is thanking US for paying them, so it is a payment we MADE - not income."""
    m = _RECEIVED_BY.search(subject or "")
    if m:
        return "in" if _same_company(m.group(1), company) else "out"
    if (direction or "incoming") != "incoming":
        return ""
    blob = f"{subject} {text_blob}"
    if _WE_PAID_BY_DEBIT.search(blob) or _WE_PAID_THANKS.search(blob):
        return "out"
    return "in"


def suggest_type(category: str, direction: str, amount, subject: str, snippet: str,
                 sender: str = "", company: str = "", body: str = ""):
    d = direction or "incoming"
    if category == "vendor_bill":
        return "bill" if d == "incoming" else None
    if category in ("payment_received", "bank_payment_advice"):
        return {"in": "customer_payment", "out": "vendor_payment"}.get(
            payment_side(subject, f"{snippet} {body}", d, company))
    if category == "quotation":
        return "estimate" if d == "outgoing" else None
    if category == "purchase_order":
        if _PO_REMINDER.search(f"{subject} {snippet}"):
            return None  # a "pending PO statement" / delivery reminder is not an order
        return "purchase_order" if d == "outgoing" else "sales_order"
    if category == "other" and amount and _EXPENSE_HINT.search(f"{subject} {snippet}"):
        return "expense"
    return None


def _ref_in(ref: str, blob: str) -> bool:
    """Is this Zoho document number written in the email text? A digit at either end of the number must not
    touch another digit (so '1234' is not found inside '51234'), but 'Invoice No26-27/016' still counts."""
    ref = ref.strip().lower()
    if len(ref) < 4:
        return False
    pre = r"(?<![0-9])" if ref[0].isdigit() else r"(?<![a-z])"
    post = r"(?![0-9])" if ref[-1].isdigit() else r"(?![a-z])"
    return re.search(pre + re.escape(ref) + post, blob) is not None


def _match(df: pd.DataFrame, spec: dict, blob: str, amount, email_date, extra_amounts=(), extra_dates=()):
    """Returns (checked, matched_reason, zoho_ref). `checked` is False when the
    email gave us nothing to compare (no amount and no reference in its text).
    `extra_amounts` / `extra_dates` come from the email's full text (see _store_body_facts)."""
    blob = (blob or "").lower()
    for col in spec["refs"]:
        if col not in df.columns:
            continue
        for ref in df[col].dropna().astype(str):
            if _ref_in(ref, blob):
                return True, "reference number", ref.strip()
    amounts_to_try = []
    for a in [amount, *extra_amounts]:
        a = _num(a)
        if a is not None and a > 0 and a not in amounts_to_try:
            amounts_to_try.append(a)
    acol = _first_col(df, spec["amount"])
    if not amounts_to_try or acol is None:
        return False, "", ""
    zamounts = pd.to_numeric(df[acol], errors="coerce")
    close = pd.DataFrame()
    for a in amounts_to_try:
        close = df[(zamounts - a).abs() <= _AMOUNT_TOLERANCE]
        if not close.empty:
            break
    if close.empty:
        return True, "", ""
    dcol = _first_col(df, spec["date"])
    when = [d for d in [email_date, *[pd.Timestamp(x, tz="UTC") for x in extra_dates if _iso(x)]]
            if d is not None and not pd.isna(d)]
    if dcol is None or not when:
        return True, "amount", ""
    dates = pd.to_datetime(close[dcol], errors="coerce", utc=True)
    near_mask = pd.Series(False, index=close.index)
    for w in when:
        near_mask = near_mask | ((dates - w).abs() <= pd.Timedelta(days=_DATE_WINDOW_DAYS))
    near = close[near_mask]
    if near.empty:
        return True, "", ""
    ref_col = _first_col(near, spec["refs"])
    return True, "amount and date", (str(near.iloc[0][ref_col]) if ref_col else "")


def find_missing(tenant: dict, days: int = 30, limit: int = 100, gmail_connector: dict = None) -> dict:
    """`gmail_connector` (optional): when given, the full text of emails that still look missing is read
    from Gmail (free) so amounts / invoice numbers written in the body are compared too."""
    with _db(tenant) as (engine, schema):
        return _find_missing(engine, schema, days, limit, company=str(tenant.get("name") or ""),
                             gmail=gmail_connector)


def _read_bodies(engine, schema, gmail, todo, facts) -> None:
    """Fetch the full text of up to _BODY_CAP emails (free Gmail reads) and remember what they say.
    Stops early after a time budget or three failures in a row (e.g. Gmail refusing) - never raises."""
    started, fails = time.monotonic(), 0
    for mid in todo[:_BODY_CAP]:
        if time.monotonic() - started > _BODY_BUDGET_SECONDS or fails >= 3:
            break
        try:
            msg = connectors_gmail.fetch_full_message(gmail, mid, include_pdf=False)
            facts[mid] = _store_body_facts(engine, schema, mid, msg.get("text") or "")
            fails = 0
        except Exception as e:
            fails += 1
            log.warning("inbox_books: could not read email %s: %s", mid, e)


def _find_missing(engine, schema, days: int, limit: int, company: str = "", gmail: dict = None) -> dict:
    out = {"gmail_synced": False, "zoho_synced": False, "items": [], "counts": {}, "body_pending": 0,
           "write_enabled": settings.INBOX_BOOKS_WRITE}
    emails = _frame(engine, schema, "emails")
    if emails is None or emails.empty:
        return out
    out["gmail_synced"] = True

    emails["_dt"] = pd.to_datetime(emails["email_date"], errors="coerce", utc=True)
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=max(1, min(int(days), 365)))
    emails = emails[emails["_dt"] >= cutoff].sort_values("_dt", ascending=False).head(600)

    frames = {t: _frame(engine, schema, s["table"]) for t, s in _SPECS.items()}
    out["zoho_synced"] = any(f is not None for f in frames.values())
    done = _actions(engine, schema)

    rows = []
    for _, e in emails.iterrows():
        mid = str(e["message_id"])
        if (mid, "") in done or any((mid, t) in done for t in RECORD_TYPES):
            continue
        subject, snippet = str(e.get("subject") or ""), str(e.get("snippet") or "")
        sender = str(e.get("sender") or "")
        category = classify(sender, subject, snippet)  # re-derived so classifier fixes apply without a re-sync
        if category == "other":
            category = str(e.get("category") or "other")
        rows.append({"mid": mid, "dt": e["_dt"], "sender": sender, "subject": subject, "snippet": snippet,
                     "category": category, "direction": str(e.get("direction") or ""),
                     "amount": _num(e.get("amount")) or parse_amount(subject) or parse_amount(snippet)})

    facts = _load_body_facts(engine, schema, [r["mid"] for r in rows])

    def evaluate(r):
        b = facts.get(r["mid"]) or {}
        rtype = suggest_type(r["category"], r["direction"], r["amount"], r["subject"], r["snippet"],
                             sender=r["sender"], company=company, body=b.get("body", ""))
        if rtype is None:
            return None
        df = frames[rtype]
        if df is None:
            return rtype, False, False
        checked, reason, _ref = _match(df, _SPECS[rtype], f"{r['subject']} {r['snippet']} {b.get('body', '')}",
                                       r["amount"], r["dt"], b.get("amounts", []), b.get("dates", []))
        return rtype, checked, bool(reason)

    for r in rows:
        r["res"] = evaluate(r)

    if gmail is not None and out["zoho_synced"]:
        todo = [r["mid"] for r in rows if r["res"] and not r["res"][2] and r["mid"] not in facts
                and frames[r["res"][0]] is not None]
        if todo:
            _read_bodies(engine, schema, gmail, todo, facts)
            for r in rows:
                if r["mid"] in facts:
                    r["res"] = evaluate(r)
        out["body_pending"] = sum(1 for r in rows if r["res"] and not r["res"][2] and r["mid"] not in facts
                                  and frames[r["res"][0]] is not None)

    for r in rows:
        if r["res"] is None:
            continue
        rtype, checked, matched = r["res"]
        if matched:
            continue
        b = facts.get(r["mid"]) or {}
        note = ""
        if frames[rtype] is None:
            note = "Zoho data for this type isn't synced yet - sync Zoho, then check again."
        elif not checked:
            note = ("Couldn't compare - no amount or reference in the email text (it may only be in an attached PDF)."
                    if r["mid"] in facts else
                    "Couldn't compare (no amount or reference found in the email).")
        shown = r["amount"] if r["amount"] is not None else (b.get("amounts") or [None])[0]
        out["items"].append({
            "message_id": r["mid"], "email_date": _iso(r["dt"]), "sender": r["sender"],
            "subject": r["subject"], "snippet": r["snippet"][:200], "category": r["category"],
            "direction": r["direction"], "suggested_type": rtype, "amount": shown,
            "checked": checked, "note": note, "read_body": r["mid"] in facts,
        })
        out["counts"][rtype] = out["counts"].get(rtype, 0) + 1
        if len(out["items"]) >= limit:
            break
    return out


# ---------------- 2. extract fields from ONE email (AI, no writes) ----------------
_FIELDS_JSON = """{
 "party_name": "the other company (vendor for bills/POs/expenses, customer for payments/quotes/sales orders)",
 "document_number": "invoice / bill / quotation / PO number, or empty",
 "date": "YYYY-MM-DD, or empty if unclear",
 "due_date": "YYYY-MM-DD, or empty",
 "currency": "INR",
 "total": <total amount as a number, or null>,
 "line_items": [{"description": "...", "quantity": <number>, "rate": <unit price number>}],
 "reference_number": "UTR / payment / other reference, or empty",
 "related_invoice_number": "for a payment: the invoice number it pays, or empty",
 "related_invoice_numbers": ["for a payment: EVERY invoice / bill number it pays, exactly as written (empty list if none)"],
 "payment_mode": "banktransfer|cash|check|creditcard|others  (for payments; else empty)",
 "gst_no": "GSTIN if present, or empty",
 "notes": "one short plain-English sentence"
}"""

_TYPE_HINT = {
    "bill": "a vendor bill we must pay",
    "customer_payment": "a payment we RECEIVED from a customer (money that came into our account)",
    "vendor_payment": "a payment WE MADE to a supplier (money that left our account); party_name is the supplier who was paid",
    "estimate": "a quotation we sent to a customer",
    "purchase_order": "a purchase order we sent to a vendor",
    "sales_order": "a purchase order a customer sent us (a sales order)",
    "expense": "a receipt for money we spent",
}


def _claude_json(prompt: str, pdf_bytes=None) -> dict:
    from anthropic import Anthropic

    headers = {}
    if settings.ANTHROPIC_WORKSPACE_ID:
        headers["anthropic-workspace-id"] = settings.ANTHROPIC_WORKSPACE_ID
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY, default_headers=headers or None)
    content = []
    if pdf_bytes:
        content.append({"type": "document", "source": {
            "type": "base64", "media_type": "application/pdf",
            "data": base64.standard_b64encode(pdf_bytes).decode()}})
    content.append({"type": "text", "text": prompt})
    msg = client.messages.create(model=settings.EXTRACT_MODEL, max_tokens=1200,
                                 messages=[{"role": "user", "content": content}])
    try:
        u = msg.usage
        billing.add_usage(settings.EXTRACT_MODEL, getattr(u, "input_tokens", 0), getattr(u, "output_tokens", 0),
                          getattr(u, "cache_read_input_tokens", 0) or 0,
                          getattr(u, "cache_creation_input_tokens", 0) or 0)
    except Exception:
        pass
    raw = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text").strip()
    raw = re.sub(r"^```(?:json)?", "", raw).strip()
    raw = re.sub(r"```$", "", raw).strip()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("not an object")
    return data


def extract_fields(record_type: str, message: dict) -> dict:
    prompt = (
        f"This email is {_TYPE_HINT[record_type]}, for an Indian business.\n"
        f"From: {message.get('sender', '')}\nSubject: {message.get('subject', '')}\n"
        f"Date: {message.get('date', '')}\n\nBody:\n{message.get('text', '')}\n\n"
        "Read the email (and the attached PDF if there is one) and reply with ONLY this JSON object:\n"
        f"{_FIELDS_JSON}\nUse only what the document actually says; leave a field empty rather than guessing."
    )
    return _claude_json(prompt, message.get("pdf"))


def _clean_fields(raw: dict) -> dict:
    items = []
    for li in (raw.get("line_items") or []):
        if not isinstance(li, dict):
            continue
        rate, qty = _num(li.get("rate")), _num(li.get("quantity")) or 1.0
        if rate is not None:
            items.append({"description": str(li.get("description") or "")[:200], "quantity": qty, "rate": rate})
    return {
        "party_name": str(raw.get("party_name") or "").strip(),
        "document_number": str(raw.get("document_number") or "").strip(),
        "date": _iso(raw.get("date")), "due_date": _iso(raw.get("due_date")),
        "currency": str(raw.get("currency") or "INR"),
        "total": _num(raw.get("total")), "line_items": items,
        "reference_number": str(raw.get("reference_number") or "").strip(),
        "related_invoice_number": str(raw.get("related_invoice_number") or "").strip(),
        "related_invoice_numbers": [str(x).strip()[:60] for x in (raw.get("related_invoice_numbers") or [])
                                    if isinstance(x, (str, int)) and str(x).strip()][:30],
        "payment_mode": str(raw.get("payment_mode") or "").strip() or "banktransfer",
        "gst_no": str(raw.get("gst_no") or "").strip(), "notes": str(raw.get("notes") or "").strip(),
    }


def _find_party(engine, schema, name: str, party_kind: str):
    """Case-insensitive match against the synced Zoho contacts (table `customers`)."""
    df = _frame(engine, schema, "customers")
    if df is None or not name or "contact_id" not in df.columns:
        return None
    want = name.strip().lower()
    if "status" in df.columns:
        df = df[df["status"].astype(str).str.lower() != "inactive"]
    for col in ("contact_name", "company_name"):
        if col not in df.columns:
            continue
        hit = df[df[col].astype(str).str.strip().str.lower() == want]
        if "contact_type" in df.columns and not hit.empty:
            typed = hit[hit["contact_type"].astype(str).str.lower() == party_kind]
            hit = typed if not typed.empty else hit
        if not hit.empty:
            r = hit.iloc[0]
            return {"contact_id": str(r["contact_id"]), "contact_name": str(r.get("contact_name") or name)}
    return None


def _invoice_candidates(engine, schema, party: str, total, invoice_no: str) -> list:
    df = _frame(engine, schema, "invoices")
    if df is None or "invoice_id" not in df.columns:
        return []
    out = []
    for _, r in df.iterrows():
        status = str(r.get("status") or "").lower()
        if status in ("paid", "void", "draft"):
            continue
        bal = _num(r.get("balance"))
        same_no = bool(invoice_no) and str(r.get("invoice_number") or "").strip().lower() == invoice_no.lower()
        same_party = bool(party) and str(r.get("customer_name") or "").strip().lower() == party.lower()
        same_amt = total is not None and bal is not None and abs(bal - float(total)) <= _AMOUNT_TOLERANCE
        if same_no or same_party or same_amt:
            out.append({"invoice_id": str(r["invoice_id"]), "invoice_number": str(r.get("invoice_number") or ""),
                        "customer_name": str(r.get("customer_name") or ""), "balance": bal,
                        "total": _num(r.get("total")), "date": _iso(r.get("date")),
                        "best": bool(same_no or same_amt)})
    out.sort(key=lambda c: (not c["best"], c["date"]))
    return out[:10]


def _bill_candidates(engine, schema, party: str, numbers, blob: str) -> list:
    """Open bills a payment we made could be settling: the supplier's own bills, plus any bill whose number
    is written in the email. Bills named in the email come first and are pre-ticked in the form."""
    df = _frame(engine, schema, "bills")
    if df is None or "bill_id" not in df.columns:
        return []
    wanted = {n.strip().lower() for n in numbers if n and n.strip()}
    blob = (blob or "").lower()
    out = []
    for _, r in df.iterrows():
        if str(r.get("status") or "").lower() in ("paid", "void", "draft"):
            continue
        bal = _num(r.get("balance"))
        if bal is not None and bal <= 0:
            continue
        number = str(r.get("bill_number") or "").strip()
        named = bool(number) and (number.lower() in wanted or _ref_in(number, blob))
        same_party = bool(party) and str(r.get("vendor_name") or "").strip().lower() == party.strip().lower()
        if named or same_party:
            out.append({"bill_id": str(r["bill_id"]), "bill_number": number,
                        "vendor_name": str(r.get("vendor_name") or ""), "balance": bal,
                        "total": _num(r.get("total")), "date": _iso(r.get("date")), "best": named})
    out.sort(key=lambda c: (not c["best"], c["date"]))
    return out[:30]


def extract(tenant: dict, gmail_connector: dict, record_type: str, message_id: str) -> dict:
    if record_type not in RECORD_TYPES:
        raise InboxError(400, "Unknown record type.")
    with _db(tenant) as (engine, schema):
        _check_email(engine, schema, message_id)
        message = connectors_gmail.fetch_full_message(gmail_connector, message_id)
        fields = _clean_fields(extract_fields(record_type, message))
        return _extract_result(engine, schema, record_type, fields, message)


def _extract_result(engine, schema, record_type: str, fields: dict, message: dict) -> dict:
    spec = _SPECS[record_type]
    party = _find_party(engine, schema, fields["party_name"], spec["party"])
    warnings = []
    if not fields["party_name"]:
        warnings.append("Couldn't find the company name - please type it in.")
    if not fields["date"]:
        warnings.append("Couldn't find the date - please enter it.")
    if fields["total"] is None and not fields["line_items"]:
        warnings.append("Couldn't find the amount - please enter it.")
    if party is None and fields["party_name"]:
        warnings.append(f"'{fields['party_name']}' isn't in your Zoho contacts yet - a new "
                        f"{spec['party']} will be created when you confirm.")
    return {
        "record_type": record_type, "fields": fields, "party_match": party,
        "invoice_candidates": _invoice_candidates(engine, schema, fields["party_name"], fields["total"],
                                                  fields["related_invoice_number"])
        if record_type == "customer_payment" else [],
        "bill_candidates": _bill_candidates(engine, schema, fields["party_name"],
                                            [fields["related_invoice_number"], *fields["related_invoice_numbers"]],
                                            f"{message.get('subject', '')} {message.get('text', '')}")
        if record_type == "vendor_payment" else [],
        "email": {"subject": message.get("subject", ""), "sender": message.get("sender", ""),
                  "date": message.get("date", ""), "has_pdf": bool(message.get("pdf"))},
        "warnings": warnings,
    }


# ---------------- Zoho calls (module-level so tests can replace them) ----------------
def _zoho_headers(token: str) -> dict:
    return {"Authorization": f"Zoho-oauthtoken {token}"}


def _zoho_get(api_domain: str, token: str, org_id: str, path: str, params=None) -> dict:
    p = {"organization_id": org_id, **(params or {})}
    r = requests.get(f"{api_domain}/books/v3/{path}", headers=_zoho_headers(token), params=p, timeout=25)
    if r.status_code == 401:
        raise InboxError(403, _RECONNECT)
    r.raise_for_status()
    return r.json()


def _zoho_post(api_domain: str, token: str, org_id: str, path: str, payload: dict) -> dict:
    r = requests.post(f"{api_domain}/books/v3/{path}", headers=_zoho_headers(token),
                      params={"organization_id": org_id}, json=payload, timeout=30)
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code == 401 or "not authorized" in str(data.get("message", "")).lower():
        raise InboxError(403, _RECONNECT)
    if r.status_code >= 400 or data.get("code", 0) != 0:
        raise InboxError(422, f"Zoho rejected it: {data.get('message') or r.text[:200]}")
    return data


_RECONNECT = ("Zoho hasn't given Ganak permission to add records yet. Go to Sources, disconnect and "
              "reconnect Zoho Books, and approve the extra permission - then try again.")


def list_accounts(zoho_connector: dict) -> dict:
    token, api_domain = connectors_zoho._valid_access_token(zoho_connector)
    raw = []
    for page in range(1, 6):  # up to 1000 accounts
        data = _zoho_get(api_domain, token, zoho_connector["org_id"], "chartofaccounts",
                         {"per_page": 200, "page": page})
        raw.extend(data.get("chartofaccounts", []))
        if not (data.get("page_context") or {}).get("has_more_page"):
            break
    accounts = [{"account_id": str(a.get("account_id")), "account_name": a.get("account_name", ""),
                 "account_type": a.get("account_type", "")} for a in raw if a.get("is_active", True)]
    spend = {"expense", "cost_of_goods_sold", "other_expense"}
    bank = {"cash", "bank", "credit_card", "other_current_asset"}
    return {"expense_accounts": [a for a in accounts if a["account_type"] in spend],
            "bank_accounts": [a for a in accounts if a["account_type"] in bank]}


# ---------------- 3. create ONE record after the user confirms ----------------
def _validate(record_type: str, f: dict) -> dict:
    spec = _SPECS[record_type]
    party = str(f.get("party_name") or "").strip()
    if not party and not f.get("contact_id"):
        raise InboxError(400, f"Enter the {spec['party']} name.")
    date = _iso(f.get("date"))
    if not date:
        raise InboxError(400, "Enter a valid date (YYYY-MM-DD).")
    cur = str(f.get("currency") or "INR").strip().upper()
    if cur not in ("INR", "RS", "\u20b9"):
        raise InboxError(400, f"This document is in {cur}. Foreign-currency records can't be added from here yet - "
                              "please add it in Zoho Books directly.")
    total = _num(f.get("total"))
    items = []
    for li in (f.get("line_items") or []):
        if not isinstance(li, dict):
            continue
        rate, qty = _num(li.get("rate")), _num(li.get("quantity")) or 1.0
        if rate is not None and rate > 0 and qty > 0:
            items.append({"description": str(li.get("description") or record_type.replace("_", " "))[:200],
                          "quantity": qty, "rate": rate})
    line_sum = round(sum(i["quantity"] * i["rate"] for i in items), 2)
    if record_type in ("customer_payment", "vendor_payment", "expense"):
        # the money that actually moved: always the total, never a sum of (pre-tax) lines
        amount = total if total is not None and total > 0 else line_sum
        items = []
    elif items:
        amount = line_sum
        if total is not None and abs(total - line_sum) > _AMOUNT_TOLERANCE:
            raise InboxError(400, f"The line items add up to {line_sum:,.2f} but the document total is {total:,.2f}. "
                                  "Add the GST/tax as its own line (or fix the rates) so they match - "
                                  "otherwise Zoho would book the wrong amount.")
    elif total is not None and total > 0:
        amount = total
        items = [{"description": str(f.get("notes") or record_type.replace("_", " "))[:200],
                  "quantity": 1.0, "rate": total}]
    else:
        amount = 0
    if not amount or amount <= 0:
        raise InboxError(400, "Enter the amount (or at least one line item with a price).")
    amount = round(amount, 2)
    if record_type == "bill":
        if not str(f.get("document_number") or "").strip():
            raise InboxError(400, "Enter the bill number.")
        if not f.get("account_id"):
            raise InboxError(400, "Choose the expense account for this bill.")
    if record_type == "expense":
        if not f.get("account_id") or not f.get("paid_through_account_id"):
            raise InboxError(400, "Choose the expense account and the account it was paid from.")
    if record_type == "customer_payment" and not f.get("deposit_account_id"):
        raise InboxError(400, "Choose the bank or cash account the payment went into.")
    bill_ids = f.get("bill_ids") or []
    if record_type == "vendor_payment":
        if not f.get("paid_through_account_id"):
            raise InboxError(400, "Choose the bank or cash account the payment was made from.")
        if (not isinstance(bill_ids, list) or len(bill_ids) > 30
                or any(not _ZOHO_ID.match(str(b)) for b in bill_ids)):
            raise InboxError(400, "The bills selected for this payment aren't valid - please re-select them.")
    return {**f, "party_name": party, "date": date, "due_date": _iso(f.get("due_date")),
            "line_items": items, "amount": amount,
            "bill_ids": [str(b) for b in bill_ids] if record_type == "vendor_payment" else []}


def _payload(record_type: str, f: dict, contact_id: str) -> dict:
    num = str(f.get("document_number") or "").strip()
    ref = str(f.get("reference_number") or "").strip()
    notes = str(f.get("notes") or "").strip()
    if record_type == "bill":
        p = {"vendor_id": contact_id, "bill_number": num, "date": f["date"], "notes": notes,
             "line_items": [{"account_id": str(f["account_id"]), "description": i["description"],
                             "rate": i["rate"], "quantity": i["quantity"]} for i in f["line_items"]]}
        if f["due_date"]:
            p["due_date"] = f["due_date"]
        if ref:
            p["reference_number"] = ref
        return p
    if record_type == "expense":
        return {"account_id": str(f["account_id"]), "paid_through_account_id": str(f["paid_through_account_id"]),
                "date": f["date"], "amount": f["amount"], "vendor_id": contact_id,
                "reference_number": ref or num, "description": notes}
    if record_type == "customer_payment":
        p = {"customer_id": contact_id, "payment_mode": f.get("payment_mode") or "banktransfer",
             "amount": f["amount"], "date": f["date"], "account_id": str(f["deposit_account_id"]),
             "reference_number": ref or num, "description": notes}
        if f.get("invoice_id"):
            p["invoices"] = [{"invoice_id": str(f["invoice_id"]),
                              "amount_applied": f.get("amount_applied", f["amount"])}]
        return p
    if record_type == "vendor_payment":
        p = {"vendor_id": contact_id, "payment_mode": f.get("payment_mode") or "banktransfer",
             "amount": f["amount"], "date": f["date"], "paid_through_account_id": str(f["paid_through_account_id"]),
             "reference_number": ref or num, "description": notes}
        if f.get("_alloc"):
            p["bills"] = f["_alloc"]
        return p
    lines = [{"name": i["description"], "rate": i["rate"], "quantity": i["quantity"]} for i in f["line_items"]]
    key = {"estimate": "customer_id", "sales_order": "customer_id", "purchase_order": "vendor_id"}[record_type]
    p = {key: contact_id, "date": f["date"], "line_items": lines, "notes": notes}
    if ref or num:
        p["reference_number"] = ref or num
    return p


def _refresh_after_create(tenant: dict, connector: dict, table: str) -> None:
    tables = [table, "bills"] if table == "vendor_payments" else [table]  # paying bills changes their balance
    try:
        connectors_zoho.run_full_sync(tenant, connector, only=[*tables, "customers"])
    except Exception as e:  # never fail a successful create over a refresh
        log.warning("inbox_books: refresh after create failed: %s", e)


def _live_contact(api_domain, token, org_id, name: str, party_kind: str):
    """Ask Zoho itself (the synced copy may be stale) for a contact with exactly this name."""
    data = _zoho_get(api_domain, token, org_id, "contacts", {"contact_name_contains": name, "per_page": 50})
    want = name.strip().lower()
    hits = [c for c in data.get("contacts", [])
            if str(c.get("contact_name") or "").strip().lower() == want and c.get("status", "active") != "inactive"]
    typed = [c for c in hits if str(c.get("contact_type") or "").lower() == party_kind]
    pick = (typed or hits or [None])[0]
    return str(pick["contact_id"]) if pick else ""


def _live_bill_exists(api_domain, token, org_id, bill_number: str) -> str:
    """Live duplicate check for bills (the synced table can be days old). Returns the number if found."""
    data = _zoho_get(api_domain, token, org_id, "bills", {"bill_number": bill_number, "per_page": 50})
    for b in data.get("bills", []):
        if str(b.get("bill_number") or "").strip().lower() == bill_number.strip().lower():
            return str(b.get("bill_number"))
    return ""


def _reserve(engine, schema, message_id: str, record_type: str) -> None:
    """Claim (email, type) BEFORE talking to Zoho. The primary key makes two tabs / a double
    click race safely: exactly one wins, the other gets a 409."""
    _ensure_actions(engine, schema)
    with engine.begin() as c:
        row = c.execute(text(f"SELECT status FROM {_qt(schema, 'inbox_actions')} WHERE message_id=:m AND record_type=:t"),
                        {"m": message_id, "t": record_type}).fetchone()
        if row and row[0] in ("created", "pending"):
            raise InboxError(409, "This email has already been added to Zoho by Ganak"
                                  if row[0] == "created" else
                                  "This email is being added right now, or a previous attempt didn't finish. "
                                  "Check Zoho Books before trying again.")
        c.execute(text(f"DELETE FROM {_qt(schema, 'inbox_actions')} WHERE message_id=:m AND record_type=:t"),
                  {"m": message_id, "t": record_type})
    try:
        _record_action_insert_only(engine, schema, message_id, record_type, "pending")
    except IntegrityError:
        raise InboxError(409, "This email is being added right now. Check Zoho Books before trying again.")


def _record_action_insert_only(engine, schema, message_id, record_type, status) -> None:
    with engine.begin() as c:
        c.execute(text(
            f"INSERT INTO {_qt(schema, 'inbox_actions')} "
            "(message_id, record_type, status, zoho_id, zoho_ref, detail, created_at) "
            "VALUES (:m, :t, :s, '', '', '', :ts)"),
            {"m": message_id, "t": record_type, "s": status, "ts": datetime.now(timezone.utc).isoformat()})


def _release(engine, schema, message_id: str, record_type: str) -> None:
    """Zoho definitely refused: free the claim so the user can fix the form and retry."""
    with engine.begin() as c:
        c.execute(text(f"DELETE FROM {_qt(schema, 'inbox_actions')} "
                       "WHERE message_id=:m AND record_type=:t AND status='pending'"),
                  {"m": message_id, "t": record_type})


def create(tenant: dict, zoho_connector: dict, record_type: str, message_id: str, fields: dict,
           allow_duplicate: bool = False) -> dict:
    if not settings.INBOX_BOOKS_WRITE:
        raise InboxError(403, "Adding records to Zoho isn't switched on for this Ganak yet.")
    if record_type not in RECORD_TYPES:
        raise InboxError(400, "Unknown record type.")
    f = _validate(record_type, fields or {})
    with _db(tenant) as (engine, schema):
        _check_email(engine, schema, message_id)
        return _create(tenant, zoho_connector, engine, schema, record_type, message_id, f, allow_duplicate)


def _allocate_to_bills(engine, schema, bill_ids, amount: float) -> list:
    """Split the money we paid over the bills the user ticked, oldest first, never more than a bill still
    owes. Anything left over stays unapplied in Zoho (it shows as an excess payment to apply later)."""
    bills = _frame(engine, schema, "bills")
    if bills is None or not {"bill_id", "balance"} <= set(bills.columns):
        raise InboxError(409, "Your synced Zoho bills aren't available - sync Zoho and try again.")
    hit = bills[bills["bill_id"].astype(str).isin(bill_ids)]
    if len(hit) != len(set(bill_ids)):
        raise InboxError(409, "One of the selected bills isn't in your synced Zoho data - sync Zoho and try again.")
    if "date" in hit.columns:
        hit = hit.sort_values("date")
    remaining, alloc = float(amount), []
    for _, r in hit.iterrows():
        bal = _num(r["balance"]) or 0.0
        if bal <= 0 or remaining <= 0:
            continue
        take = round(min(bal, remaining), 2)
        alloc.append({"bill_id": str(r["bill_id"]), "amount_applied": take})
        remaining = round(remaining - take, 2)
    if not alloc:
        raise InboxError(400, "The bills you picked have nothing left to pay - untick them to record an unapplied payment.")
    return alloc


def _create(tenant, zoho_connector, engine, schema, record_type, message_id, f, allow_duplicate) -> dict:
    spec = _SPECS[record_type]
    token, api_domain = connectors_zoho._valid_access_token(zoho_connector)
    org_id = zoho_connector["org_id"]

    if not allow_duplicate:
        df = _frame(engine, schema, spec["table"])
        if df is not None:
            _c, reason, ref = _match(df, spec, f"{f.get('document_number', '')} {f.get('reference_number', '')}",
                                     f["amount"], pd.Timestamp(f["date"], tz="UTC"))
            if reason:
                raise InboxError(409, f"Zoho already has a matching {record_type.replace('_', ' ')}"
                                      f"{' (' + ref + ')' if ref else ''}. Tick 'add anyway' if it's really different.")
        if record_type == "bill":  # live check: the synced copy can be stale
            try:
                live = _live_bill_exists(api_domain, token, org_id, str(f["document_number"]))
            except InboxError:
                raise
            except Exception:
                raise InboxError(502, "Couldn't double-check Zoho for an existing bill with this number - "
                                      "nothing was added. Please try again.")
            if live:
                raise InboxError(409, f"Zoho already has a matching bill ({live}). "
                                      "Tick 'add anyway' if it's really different.")

    applied = None
    if record_type == "customer_payment" and f.get("invoice_id"):
        inv = _frame(engine, schema, "invoices")
        if inv is not None and "invoice_id" in inv.columns and "balance" in inv.columns:
            hit = inv[inv["invoice_id"].astype(str) == str(f["invoice_id"])]
            bal = _num(hit.iloc[0]["balance"]) if not hit.empty else None
            if bal is not None:
                applied = round(min(f["amount"], max(bal, 0)), 2)
        f = {**f, "amount_applied": applied if applied is not None else f["amount"]}

    if record_type == "vendor_payment" and f.get("bill_ids"):
        f = {**f, "_alloc": _allocate_to_bills(engine, schema, f["bill_ids"], f["amount"])}

    _reserve(engine, schema, message_id, record_type)  # from here on only ONE request can proceed
    posted = False  # becomes True once we've sent anything that could have created a record
    try:
        contact_id = str(f.get("contact_id") or "")
        if not contact_id:
            found = _find_party(engine, schema, f["party_name"], spec["party"])
            contact_id = found["contact_id"] if found else _live_contact(api_domain, token, org_id, f["party_name"], spec["party"])
        if not contact_id:
            body = {"contact_name": f["party_name"], "contact_type": spec["party"]}
            if str(f.get("gst_no") or "").strip():
                body["gst_no"] = str(f["gst_no"]).strip()
            posted = True
            made = _zoho_post(api_domain, token, org_id, "contacts", body)
            contact_id = str((made.get("contact") or {}).get("contact_id") or "")
            if not contact_id:
                raise InboxError(422, "Zoho didn't return the new contact - nothing was added.")
        payload = _payload(record_type, f, contact_id)
        posted = True
        data = _zoho_post(api_domain, token, org_id, spec["endpoint"], payload)
    except InboxError:
        _release(engine, schema, message_id, record_type)  # Zoho said no: safe to retry after fixing
        raise
    except Exception as e:
        if not posted:  # failed while only reading from Zoho: nothing was created
            _release(engine, schema, message_id, record_type)
            raise InboxError(502, "Couldn't reach Zoho Books - nothing was added. Please try again.") from e
        # Timeout / connection drop after a write was sent: Zoho MAY have created it.
        # Keep the claim so a retry can't double-book.
        log.exception("inbox_books: ambiguous failure creating %s for email %s", record_type, message_id)
        raise InboxError(502, "Zoho didn't answer in time, so Ganak can't tell whether the record was created. "
                              "Check Zoho Books first - it stays blocked here to avoid a double entry.") from e

    rec = data.get(spec["key"]) or data.get("payment") or {}
    zoho_id = str(rec.get(spec["key"] + "_id") or rec.get("payment_id") or "")
    zoho_no = str(rec.get(spec["key"] + "_number") or rec.get("bill_number") or rec.get("reference_number") or "")
    _record_action(engine, schema, message_id, record_type, "created", zoho_id, zoho_no,
                   f"{f['party_name']} {f['amount']}")
    _refresh_after_create(tenant, zoho_connector, spec["table"])
    log.info("inbox_books: created %s %s for tenant %s from email %s", record_type, zoho_id, tenant["id"], message_id)
    return {"ok": True, "record_type": record_type, "zoho_id": zoho_id, "zoho_number": zoho_no,
            "message": f"Added to Zoho Books{' as ' + zoho_no if zoho_no else ''}."}
