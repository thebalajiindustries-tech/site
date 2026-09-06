"""Shared classification + amount parsing for a tenant's finance emails.

Generalised from backend/connectors/classify.py (Balaji's own local script,
which hardcoded Balaji's own addresses as "self"). Here `self_addr` is the
Gmail address the tenant actually connected, discovered from Google's
userinfo endpoint at connect time -- so this works for any tenant, not just
Balaji.
"""
import re

_AMOUNT = re.compile(r"(?:₹|Rs\.?|INR)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", re.IGNORECASE)


def parse_amount(text: str):
    if not text:
        return None
    m = _AMOUNT.search(text)
    if not m:
        return None
    raw = m.group(1).replace(",", "")
    try:
        return round(float(raw), 2)
    except ValueError:
        return None


def sender_domain(sender: str) -> str:
    m = re.search(r"@([\w.\-]+)", sender or "")
    return m.group(1).lower() if m else ""


def classify(sender: str, subject: str, snippet: str) -> str:
    s = (subject or "").lower()
    body = (snippet or "").lower()
    dom = sender_domain(sender)
    text = f"{s} {body}"

    if "zoho-books" in dom and "payment received" in text:
        return "payment_received"
    if "payment advice" in s or "bank" in dom:
        return "bank_payment_advice"
    if "balance confirmation" in text or "balance confirm" in text:
        return "balance_confirmation"
    if "quotation" in text or "quote" in s:
        return "quotation"
    if "purchase order" in text or re.search(r"\bpo\b", s):
        return "purchase_order"
    if any(k in text for k in ("pending bill", "make payment", "amount due", "outstanding payment", "invoice", "bill")):
        return "vendor_bill"
    return "other"


def direction(sender: str, label_ids, self_addr: str) -> str:
    labels = set(label_ids or [])
    if "SENT" in labels:
        return "outgoing"
    addr = re.search(r"<([^>]+)>", sender or "")
    candidate = (addr.group(1) if addr else sender or "").strip().lower()
    if self_addr and candidate == self_addr.strip().lower():
        return "outgoing"
    return "incoming"
