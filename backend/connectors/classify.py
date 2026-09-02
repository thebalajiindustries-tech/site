"""Shared classification + amount parsing for Balaji's finance emails.

Tuned to the real senders seen in the account:
  - message-service@sender.zoho-books.in  -> Zoho Books payment-received notices
  - *@deutsche.bank.in                     -> bank payment advices
  - vendor domains / gmail                 -> bills, balance confirmations, quotations, POs
"""
import re

SELF = {"thebalajiindustries7333@gmail.com", "thebalajiindustries@gmail.com"}

# first ₹ / Rs / INR amount in a piece of text (handles messy Indian formatting)
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
    if "deutsche.bank" in dom or "payment advice" in s:
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


def direction(sender: str, label_ids) -> str:
    labels = set(label_ids or [])
    if "SENT" in labels or sender_domain(sender) and sender.lower().split()[-1].strip("<>") in SELF:
        return "outgoing"
    # sender may be "NAME <addr>"
    addr = re.search(r"<([^>]+)>", sender or "")
    if addr and addr.group(1).lower() in SELF:
        return "outgoing"
    return "incoming"
