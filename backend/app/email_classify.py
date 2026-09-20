"""Shared classification + amount parsing for a tenant's finance emails.

Generalised from backend/connectors/classify.py (Balaji's own local script,
which hardcoded Balaji's own addresses as "self"). Here `self_addr` is the
Gmail address the tenant actually connected, discovered from Google's
userinfo endpoint at connect time -- so this works for any tenant, not just
Balaji.
"""
import re

# "Rs 1,000", "Rs.1000", "₹3,24,941.00", "INR 500" -- not the "rs" inside a word like "Cars 500"
_AMOUNT = re.compile(r"(?:₹|(?<![A-Za-z])Rs\.?|(?<![A-Za-z])INR)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", re.IGNORECASE)
# "1,50,000.00 INR", "25000/-"
_AMOUNT_AFTER = re.compile(r"(?<![0-9,.])([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(?:INR\b|/-)", re.IGNORECASE)
# "Amount credited: 25,000.00", "Total 11800.00", "Net payable - 500.50" (needs the .00 so a bare
# "Invoice 26-27" or a phone number is never mistaken for money)
_AMOUNT_LABELLED = re.compile(
    r"(?:amount|total|net payable|net amount|paid|credited|received|debited|remitted)"
    r"\s*(?:\(?(?:inr|rs\.?|₹)\)?)?\s*[:\-]?\s*([0-9][0-9,]*\.[0-9]{2})(?![0-9])", re.IGNORECASE)


def _to_float(raw: str):
    try:
        v = round(float(raw.replace(",", "")), 2)
    except ValueError:
        return None
    return v if v > 0 else None


def parse_amount(text: str):
    if not text:
        return None
    m = _AMOUNT.search(text)
    return _to_float(m.group(1)) if m else None


def parse_amounts(text: str, limit: int = 20) -> list:
    """Every money amount an email's text mentions (in the order found, no repeats)."""
    if not text:
        return []
    found = []
    for rx in (_AMOUNT, _AMOUNT_AFTER, _AMOUNT_LABELLED):
        for m in rx.finditer(text):
            v = _to_float(m.group(1))
            if v is not None and v not in found:
                found.append(v)
    return found[:limit]


_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_D_NUM = re.compile(r"(?<![0-9])(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})(?![0-9])")          # 31/08/2026 (day first)
_D_ISO = re.compile(r"(?<![0-9])(\d{4})-(\d{2})-(\d{2})(?![0-9])")                           # 2026-08-31
_D_DMY = re.compile(r"(?<![0-9])(\d{1,2})(?:st|nd|rd|th)?[ \-]([A-Za-z]{3})[a-z]*[ ,\-]+(\d{4})")  # 31 Aug 2026
_D_MDY = re.compile(r"\b([A-Za-z]{3})[a-z]*\.? (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})")          # Aug 31, 2026


def parse_dates(text: str, limit: int = 12) -> list:
    """Calendar dates written in an email, as YYYY-MM-DD (Indian day-first order for 31/08/2026)."""
    from datetime import date
    if not text:
        return []
    out = []

    def add(y, m, d):
        try:
            iso = date(int(y), int(m), int(d)).isoformat()
        except (ValueError, TypeError):
            return
        if iso not in out:
            out.append(iso)

    for m in _D_NUM.finditer(text):
        add(m.group(3), m.group(2), m.group(1))
    for m in _D_ISO.finditer(text):
        add(m.group(1), m.group(2), m.group(3))
    for m in _D_DMY.finditer(text):
        mon = _MONTHS.get(m.group(2).lower())
        if mon:
            add(m.group(3), mon, m.group(1))
    for m in _D_MDY.finditer(text):
        mon = _MONTHS.get(m.group(1).lower())
        if mon:
            add(m.group(3), mon, m.group(2))
    return out[:limit]


def sender_domain(sender: str) -> str:
    m = re.search(r"@([\w.\-]+)", sender or "")
    return m.group(1).lower() if m else ""


_PAYMENT_DONE = re.compile(
    r"payment (?:has been |was |is )?(?:received|credited)|remittance|"
    r"amount (?:has been )?(?:credited|received)|credited to (?:your|the) (?:account|a/c)|"
    r"(?:we have|we've) received your payment|thank you for your payment|payment receipt|receipt for (?:your )?payment",
    re.IGNORECASE)
_PAYMENT_DUE = re.compile(r"amount due|payment (?:is )?due|overdue|please (?:pay|make payment)|pending (?:bill|payment)|"
                          r"outstanding payment|payment reminder", re.IGNORECASE)


def classify(sender: str, subject: str, snippet: str) -> str:
    s = (subject or "").lower()
    body = (snippet or "").lower()
    dom = sender_domain(sender)
    text = f"{s} {body}"

    if "zoho-books" in dom and "payment received" in text:
        return "payment_received"
    if "payment advice" in s or "bank" in dom:
        return "bank_payment_advice"
    # Payment emails that don't come from Zoho or a bank (a customer's remittance, a Razorpay
    # receipt, "we have received your payment"...). They usually also say "invoice", so they must be
    # caught BEFORE the bill rule below or they'd be filed as vendor bills.
    if _PAYMENT_DONE.search(text) and not _PAYMENT_DUE.search(text):
        return "payment_received"
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
