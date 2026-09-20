"""Inbox -> Books ("check my Gmail and add what's missing to Zoho Books", 20 Sept 2026).
No real Gmail / Zoho / Claude calls: connectors_gmail.fetch_full_message,
inbox_books.extract_fields, inbox_books._zoho_get/_zoho_post and
connectors_zoho.run_full_sync are all replaced.

Confirms: the Ask box points to the new page instead of refusing; find_missing
lists only emails with no matching Zoho record (by reference number, or amount +
date) and hides handled/dismissed ones; extract() proposes fields without
writing; create() is refused while INBOX_BOOKS_WRITE is off, validates input,
creates the missing contact, posts the right Zoho payload, blocks duplicates and
a second create for the same email; the reconnect message shows when Zoho says
the token isn't authorized.
"""
import os
import sys
import pathlib
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

os.environ["GANAK_SKIP_DOTENV"] = "1"
os.environ["SEED_DEMO"] = "0"
os.environ["CONTROL_DB_PATH"] = "/tmp/ganak_control_inbox_test.db"
os.environ["TENANTS_DIR"] = "/tmp/ganak_tenants_inbox_test"
os.environ["DATABASE_URL"] = "sqlite:////tmp/ganak_demo_inbox_test.db"
os.environ["ZOHO_OAUTH_CLIENT_ID"] = "fake-zoho-client-id"
os.environ["ZOHO_OAUTH_CLIENT_SECRET"] = "fake-zoho-secret"
os.environ["GOOGLE_OAUTH_CLIENT_ID"] = "fake-google-client-id"
os.environ["GOOGLE_OAUTH_CLIENT_SECRET"] = "fake-google-secret"
os.environ["PUBLIC_API_BASE_URL"] = "https://api.vidmahitech.com"
os.environ["PUBLIC_APP_BASE_URL"] = "https://app.vidmahitech.com"
os.environ["INBOX_BOOKS_WRITE"] = "0"

for f in ("/tmp/ganak_control_inbox_test.db", "/tmp/ganak_demo_inbox_test.db"):
    try:
        os.remove(f)
    except FileNotFoundError:
        pass

import pandas as pd  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app import tenancy, crypto, seed, inbox_books, connectors_gmail, connectors_zoho, config, email_classify  # noqa: E402
from app.main import app  # noqa: E402

seed.bootstrap()
client = TestClient(app, follow_redirects=False)
fails = []


def check(name, cond):
    print(("PASS" if cond else "FAIL") + " - " + name)
    if not cond:
        fails.append(name)


# ---------- unit: intent detector ----------
check("intent: the exact question the user asked",
      inbox_books.looks_like_inbox_request("in Gmail recently got one mail check it and if this not added in zoho book add it"))
check("intent: 'add my latest email bills to Zoho Books'",
      inbox_books.looks_like_inbox_request("add my latest email bills to Zoho Books"))
check("intent: normal analytics question is NOT hijacked",
      not inbox_books.looks_like_inbox_request("what is my total revenue this month?"))
for q in ("how many emails are in Zoho books", "add up my invoice totals vs zoho books",
          "when did gmail last sync with Zoho Books", "which emails were recorded in Zoho"):
    check(f"intent: analytics question not hijacked: {q}", not inbox_books.looks_like_inbox_request(q))
check("intent: 'who owes me money' not hijacked",
      not inbox_books.looks_like_inbox_request("who owes me money from Zoho invoices"))

# ---------- unit: suggest_type ----------
check("vendor bill incoming -> bill", inbox_books.suggest_type("vendor_bill", "incoming", 100, "", "") == "bill")
check("payment received incoming -> customer_payment",
      inbox_books.suggest_type("payment_received", "incoming", 100, "", "") == "customer_payment")
check("quotation outgoing -> estimate", inbox_books.suggest_type("quotation", "outgoing", 5, "", "") == "estimate")
check("PO incoming -> sales order", inbox_books.suggest_type("purchase_order", "incoming", 5, "", "") == "sales_order")
check("PO outgoing -> purchase order", inbox_books.suggest_type("purchase_order", "outgoing", 5, "", "") == "purchase_order")
check("KSB 'Pending Purchase Order Statement' reminder is not a sales order",
      inbox_books.suggest_type("purchase_order", "incoming", None, "Pending Purchase Order Statement - KSB", "Dear Vendors, ...") is None)
check("receipt-ish 'other' with amount -> expense",
      inbox_books.suggest_type("other", "incoming", 500, "Your receipt from Uber", "") == "expense")
check("random newsletter -> nothing", inbox_books.suggest_type("other", "incoming", None, "Weekly news", "") is None)

# ---------- unit: reading amounts / dates out of an email's text ----------
pa = email_classify.parse_amounts
check("amounts: Indian formatting, Rs, INR, labelled",
      pa("Payment Received \u20b93,24,941.00 Invoice No26-27/016. Total 11,800.00. 25000/- and 1,500.50 INR") == [324941.0, 25000.0, 1500.5, 11800.0]
      or set(pa("Payment Received \u20b93,24,941.00 Invoice No26-27/016. Total 11,800.00. 25000/- and 1,500.50 INR")) == {324941.0, 11800.0, 25000.0, 1500.5})
check("amounts: 'Cars 500' and invoice numbers are not money", pa("Cars 500 Invoice 26-27 ref 12345") == [])
check("amounts: snippet glitch '3,24941.00' still reads as 324941", pa("Payment Received \u20b93,24941.00") == [324941.0])
check("dates: day-first, ISO and month-name formats",
      email_classify.parse_dates("Payment Date31/08/2026, on 2026-09-01, 5th Sep 2026 and Sep 7, 2026")
      == ["2026-08-31", "2026-09-01", "2026-09-05", "2026-09-07"])
check("dates: impossible date ignored", email_classify.parse_dates("31/02/2026") == [])
check("classify: payment email that also says 'invoice' is a PAYMENT, not a vendor bill",
      email_classify.classify("a@cust.com", "Payment received for invoice INV-1", "we have received your payment") == "payment_received")
check("classify: a genuine payment-due reminder is still a bill",
      email_classify.classify("a@v.com", "Invoice INV-2 payment due", "amount due Rs 500") == "vendor_bill")
ps = inbox_books.payment_side
check("payment side: 'Payment Received by <supplier>' (we paid) -> out",
      ps("Payment Received by OJAS ENTERPISES - Sent Using Zoho Books", "", "incoming", "The Balaji Industries") == "out")
check("payment side: same subject naming OUR company -> in",
      ps("Payment Received by THE BALAJI INDUSTRIES - Sent Using Zoho Books", "", "incoming", "Balaji Industries") == "in")
check("payment side: bank/customer payment advice -> in", ps("E3S123 Payment advice", "", "incoming", "Inbox Co") == "in")
check("payment side: bank debit alert -> out", ps("Alert", "Rs 500 debited from your account", "incoming", "Inbox Co") == "out")
check("payment side: outgoing mail -> nothing to book", ps("Payment advice", "", "outgoing", "Inbox Co") == "")

# ---------- tenant with synced Gmail + Zoho data ----------
r = client.post("/auth/register", json={"email": "inbox@example.com", "password": "pass123",
                                          "company": "Inbox Co", "location": ""})
check("tenant registers", r.status_code == 200)
headers = {"Authorization": f"Bearer {r.json()['token']}"}
tid = tenancy.get_user_by_email("inbox@example.com")["tenant_id"]
tenant = tenancy.get_tenant(tid)

engine, schema = connectors_zoho._engine_for_tenant(tenant)
now = datetime.now(timezone.utc)


def emails_row(mid, days_ago, sender, subject, category, direction, amount, snippet=""):
    return {"message_id": mid, "thread_id": "t" + mid, "email_date": now - timedelta(days=days_ago),
            "sender": sender, "sender_domain": "x.com", "recipients": "me@inbox.co", "subject": subject,
            "snippet": snippet, "direction": direction, "category": category, "amount": amount, "labels": "INBOX"}


emails = pd.DataFrame([
    emails_row("m-bill-missing", 1, "Acme Supplies <bill@acme.com>", "Invoice INV-9001 for Rs 11800", "vendor_bill", "incoming", 11800),
    emails_row("m-bill-inzoho", 2, "Beta Traders <a@beta.com>", "Invoice BT-77 for Rs 5000", "vendor_bill", "incoming", 5000),
    emails_row("m-pay-missing", 3, "HDFC <alerts@hdfc.com>", "Payment received Rs 25000", "bank_payment_advice", "incoming", 25000),
    emails_row("m-pay-inzoho", 4, "Client One <c@one.com>", "Payment received Rs 7000", "payment_received", "incoming", 7000),
    emails_row("m-quote-missing", 5, "me@inbox.co", "Quotation Q-55 for Rs 90000", "quotation", "outgoing", 90000),
    emails_row("m-noamount", 6, "Gamma <g@gamma.com>", "Invoice attached", "vendor_bill", "incoming", None),
    emails_row("m-news", 7, "News <n@news.com>", "Weekly digest", "other", "incoming", None),
    emails_row("m-dup", 2, "Beta Traders <a@beta.com>", "Re: BT-77 copy", "other", "incoming", None),
    emails_row("m-exp", 2, "Uber <r@uber.com>", "Ride", "other", "incoming", None),
    emails_row("m-noperm", 2, "Acme Supplies <a@acme.com>", "Hello", "other", "incoming", None),
    emails_row("m-mismatch", 2, "Acme Supplies <a@acme.com>", "Hello2", "other", "incoming", None),
    emails_row("m-usd", 2, "Acme Supplies <a@acme.com>", "Hello3", "other", "incoming", None),
    emails_row("m-timeout", 2, "Acme Supplies <a@acme.com>", "Hello4", "other", "incoming", None),
    emails_row("m-reject", 2, "Acme Supplies <a@acme.com>", "Hello5", "other", "incoming", None),
    emails_row("m-pay2", 2, "Client One <c@one.com>", "Hello6", "other", "incoming", None),
    emails_row("m-live", 2, "Acme Supplies <a@acme.com>", "Hello7", "other", "incoming", None),
    # a supplier's Zoho Books receipt: WE paid them -> vendor payment, never income
    emails_row("m-vp-inzoho", 3, "message-service@sender.zoho-books.in", "Payment Received by OJAS ENTERPISES  - Sent Using Zoho Books",
               "payment_received", "incoming", 324941.0,
               "Payment Received Dear INBOX CO, Thank you for your payment. Payment Received \u20b93,24941.00 Invoice No26-27/"),
    emails_row("m-vp-missing", 3, "message-service@sender.zoho-books.in", "Payment Received by OJAS ENTERPISES  - Sent Using Zoho Books",
               "payment_received", "incoming", 55000.0,
               "Payment Received Dear INBOX CO, Thank you for your payment. Payment Received \u20b955,000.00 Invoice No26-27/"),
    # nothing useful in subject/snippet: the amount / invoice number is only in the body
    emails_row("m-body-inzoho", 2, "Acme Supplies <bill@acme.com>", "Your invoice is attached", "vendor_bill", "incoming", None,
               "Dear customer, please find the attached document"),
    emails_row("m-body-missing", 2, "Acme Supplies <bill@acme.com>", "Your invoice is attached", "vendor_bill", "incoming", None,
               "Dear customer, please find the attached document"),
    emails_row("m-body-fail", 2, "Acme Supplies <bill@acme.com>", "Invoice reminder", "vendor_bill", "incoming", None, "hello"),
    emails_row("m-debit", 2, "alerts@somebank.com", "Transaction alert", "bank_payment_advice", "incoming", None,
               "Rs 4321.00 debited from your account"),
    emails_row("m-old", 90, "Old Co <o@old.com>", "Invoice OLD-1 for Rs 100", "vendor_bill", "incoming", 100),
])
emails.to_sql("emails", engine, schema=schema, if_exists="replace", index=False)
_d = lambda n: (now - timedelta(days=n)).strftime("%Y-%m-%d")  # noqa: E731
pd.DataFrame([
    {"bill_id": "b1", "bill_number": "BT-77", "total": 5000.0, "date": _d(2), "vendor_name": "Beta Traders", "status": "paid", "balance": 0.0},
    {"bill_id": "vb1", "bill_number": "26-27/016", "total": 100000.0, "date": _d(40), "vendor_name": "OJAS ENTERPISES", "status": "open", "balance": 100000.0},
    {"bill_id": "vb2", "bill_number": "26-27/017", "total": 224941.0, "date": _d(38), "vendor_name": "OJAS ENTERPISES", "status": "open", "balance": 224941.0},
    {"bill_id": "vb3", "bill_number": "26-27/099", "total": 777.0, "date": _d(30), "vendor_name": "OJAS ENTERPISES", "status": "open", "balance": 777.0},
    {"bill_id": "vb4", "bill_number": "ACM-5555", "total": 24780.0, "date": _d(2), "vendor_name": "Acme Supplies", "status": "open", "balance": 24780.0},
]).to_sql("bills", engine, schema=schema, if_exists="replace", index=False)
# the supplier payment was made 15 days ago; its receipt only reached Gmail 3 days ago
pd.DataFrame([{"payment_id": "vp1", "payment_number": "VP-1", "amount": 324941.0, "date": _d(15)}]) \
    .to_sql("vendor_payments", engine, schema=schema, if_exists="replace", index=False)
pd.DataFrame([{"payment_id": "p1", "payment_number": "PMT-1", "amount": 7000.0, "date": (now - timedelta(days=5)).strftime("%Y-%m-%d")}]) \
    .to_sql("payments", engine, schema=schema, if_exists="replace", index=False)
pd.DataFrame([{"estimate_id": "e1", "estimate_number": "Q-OTHER", "total": 1.0, "date": "2020-01-01"}]) \
    .to_sql("estimates", engine, schema=schema, if_exists="replace", index=False)
pd.DataFrame([
    {"contact_id": "c-acme", "contact_name": "Acme Supplies", "contact_type": "vendor"},
    {"contact_id": "c-cust", "contact_name": "Client One", "contact_type": "customer"},
]).to_sql("customers", engine, schema=schema, if_exists="replace", index=False)
pd.DataFrame([{"invoice_id": "i1", "invoice_number": "INV-100", "customer_name": "HDFC Client", "status": "sent",
               "balance": 25000.0, "total": 25000.0, "date": "2026-09-01"},
              {"invoice_id": "i2", "invoice_number": "INV-200", "customer_name": "Client One", "status": "sent",
               "balance": 1000.0, "total": 1000.0, "date": "2026-09-02"}]) \
    .to_sql("invoices", engine, schema=schema, if_exists="replace", index=False)

# ---------- connectors (fake) so the routes can find them ----------
r = client.get("/inbox-books/missing", headers=headers)
check("missing: 400 until Gmail + Zoho are connected", r.status_code == 400)

tenancy.upsert_connector(tid, "gmail", refresh_token_enc=crypto.encrypt("g-refresh"),
                         access_token_enc=crypto.encrypt("g-acc"), token_expires_at=9999999999,
                         account_label="inbox@example.com")
tenancy.upsert_connector(tid, "zoho", refresh_token_enc=crypto.encrypt("z-refresh"),
                         access_token_enc=crypto.encrypt("z-acc"), token_expires_at=9999999999,
                         org_id="ORG1", account_label="Inbox Co", scopes="https://www.zohoapis.in")

gmail_reads = []
BODIES = {
    "m-vp-inzoho": f"Payment Received Dear INBOX CO, Thank you for your payment. Payment Received \u20b93,24,941.00 Invoice No26-27/016, 26-27/017 Payment Date{(now - timedelta(days=15)):%d/%m/%Y}",
    "m-vp-missing": f"Payment Received \u20b955,000.00 Invoice No26-27/050 Payment Date{(now - timedelta(days=4)):%d/%m/%Y}",
    "m-body-inzoho": "Tax invoice ACM-5555 dated today. Grand total Rs 24,780.00. Please pay within 15 days.",
    "m-body-missing": "Tax invoice QQ-4242. Amount payable Rs 9,999.00. Please pay soon.",
    "m-noamount": "Thanks for your business.",
}


def fake_full(connector, message_id, include_pdf=True):
    gmail_reads.append((message_id, include_pdf))
    if message_id == "m-body-fail":
        raise RuntimeError("gmail said no")
    return {"subject": "s", "sender": "x", "date": "", "text": BODIES.get(message_id, ""), "pdf": None}


connectors_gmail.fetch_full_message = fake_full

live_calls = []
live_state = {"bills": [], "contacts": []}


def fake_get(api, tok, org, path, params=None):
    live_calls.append((path, params))
    if path == "bills":
        return {"bills": live_state["bills"]}
    if path == "contacts":
        return {"contacts": live_state["contacts"]}
    return {}


inbox_books._zoho_get = fake_get

# ---------- Ask points to the new page (no refusal, no charge) ----------
before = tenancy.get_balance(tid)
r = client.post("/ask", json={"question": "in Gmail recently got one mail check it and if this not added in zoho book add it"},
                headers=headers)
check("ask: intent question returns 200 (not the 'can only answer' refusal)", r.status_code == 200)
ans = r.json().get("answer", "")
check("ask: answer points to Inbox -> Books", "Inbox" in ans and "Books" in ans)
check("ask: mentions how many are missing", "recent email" in ans)
check("ask: not charged", tenancy.get_balance(tid) == before and r.json().get("cost_inr") == 0)

# ---------- find_missing ----------
r = client.get("/inbox-books/missing?days=30", headers=headers)
check("missing: 200", r.status_code == 200)
data = r.json()
ids = {i["message_id"]: i for i in data["items"]}
check("missing: gmail + zoho flagged as synced", data["gmail_synced"] and data["zoho_synced"])
check("missing: bill with no Zoho bill is listed", "m-bill-missing" in ids and ids["m-bill-missing"]["suggested_type"] == "bill")
check("missing: bill already in Zoho (reference number) is hidden", "m-bill-inzoho" not in ids)
check("missing: bank payment with no match is listed", ids.get("m-pay-missing", {}).get("suggested_type") == "customer_payment")
check("missing: payment matched by amount + date is hidden", "m-pay-inzoho" not in ids)
check("missing: quotation with no estimate is listed", ids.get("m-quote-missing", {}).get("suggested_type") == "estimate")
check("missing: email with no amount is listed but flagged 'couldn't compare'",
      "m-noamount" in ids and ids["m-noamount"]["checked"] is False and ids["m-noamount"]["note"])
check("missing: newsletter not listed", "m-news" not in ids)
check("missing: email older than 30 days not listed", "m-old" not in ids)
check("missing: write flag reported off", data["write_enabled"] is False)
check("missing: counts add up", data["counts"].get("bill") == 4 and data["counts"].get("customer_payment") == 1)

# --- full email text is checked too (free Gmail read, PDF not downloaded) ---
check("body: an email whose invoice number is only in its text is matched to the Zoho bill and hidden",
      "m-body-inzoho" not in ids)
check("body: an email with an amount only in its text is listed WITH that amount, as compared",
      ids.get("m-body-missing", {}).get("amount") == 9999.0 and ids["m-body-missing"]["checked"] is True
      and ids["m-body-missing"]["read_body"] is True)
check("body: an email that says nothing useful even in its text stays 'couldn't compare' and says so",
      ids["m-noamount"]["checked"] is False and "email text" in ids["m-noamount"]["note"])
check("body: a Gmail read failure doesn't break the list", "m-body-fail" in ids)
check("body: emails were read WITHOUT downloading PDFs", gmail_reads and all(pdf is False for _m, pdf in gmail_reads))
first_reads = len(gmail_reads)
client.get("/inbox-books/missing?days=30", headers=headers)
check("body: text already read is remembered (only the failed one is retried)",
      [m for m, _p in gmail_reads[first_reads:]] == ["m-body-fail"])

# --- payment emails ---
check("payments: Zoho receipt from a SUPPLIER is a vendor payment, not income",
      ids.get("m-vp-missing", {}).get("suggested_type") == "vendor_payment")
check("payments: that supplier payment is matched to the Zoho payment even though its date is older "
      "than the email (date read from the text)", "m-vp-inzoho" not in ids)
check("payments: bank debit alert -> vendor payment", ids.get("m-debit", {}).get("suggested_type") == "vendor_payment")
check("payments: money received is still a customer payment", ids["m-pay-missing"]["suggested_type"] == "customer_payment")
check("missing: vendor payments counted", data["counts"].get("vendor_payment") == 2)

r = client.get("/inbox-books/status", headers=headers)
check("status reports both connected", r.json()["gmail_connected"] and r.json()["zoho_connected"])

# ---------- dismiss ----------
r = client.post("/inbox-books/dismiss", json={"message_id": "m-noamount"}, headers=headers)
check("dismiss ok", r.status_code == 200)
ids = {i["message_id"] for i in client.get("/inbox-books/missing", headers=headers).json()["items"]}
check("dismissed email disappears from the list", "m-noamount" not in ids)

# ---------- extract (mocked Gmail + Claude): reads, charges, never writes ----------
posted = []
inbox_books._zoho_post = lambda api, tok, org, path, payload: posted.append((path, payload)) or {}
connectors_gmail.fetch_full_message = lambda connector, message_id, include_pdf=True: {
    "subject": "Invoice INV-9001", "sender": "Acme Supplies <bill@acme.com>", "date": "Mon, 21 Sep 2026",
    "text": "Please pay Rs 11800. Bills 26-27/016 and 26-27/017 are settled.", "pdf": None}
inbox_books.extract_fields = lambda record_type, message: {
    "party_name": "Acme Supplies", "document_number": "INV-9001", "date": "2026-09-19", "due_date": "2026-10-19",
    "total": 11800, "line_items": [{"description": "Widgets", "quantity": 2, "rate": 5900}],
    "gst_no": "33ABCDE1234F1Z5", "notes": "Widgets order"}
r = client.post("/inbox-books/extract", json={"message_id": "m-bill-missing", "record_type": "bill"}, headers=headers)
check("extract: 200", r.status_code == 200)
ex = r.json()
check("extract: fields cleaned", ex["fields"]["party_name"] == "Acme Supplies" and ex["fields"]["total"] == 11800.0
      and ex["fields"]["line_items"][0]["rate"] == 5900.0)
check("extract: existing vendor matched from Zoho contacts", (ex["party_match"] or {}).get("contact_id") == "c-acme")
check("extract: no warnings when everything was found", ex["warnings"] == [])
check("extract: nothing was written to Zoho", posted == [])
r = client.post("/inbox-books/extract", json={"message_id": "x", "record_type": "nonsense"}, headers=headers)
check("extract: unknown record type -> 400", r.status_code == 400)

inbox_books.extract_fields = lambda record_type, message: {
    "party_name": "HDFC Client", "date": "2026-09-18", "total": 25000, "reference_number": "UTR123",
    "related_invoice_number": "INV-100", "payment_mode": "banktransfer"}
r = client.post("/inbox-books/extract", json={"message_id": "m-pay-missing", "record_type": "customer_payment"}, headers=headers)
ex = r.json()
check("extract payment: suggests the matching open invoice",
      ex["invoice_candidates"] and ex["invoice_candidates"][0]["invoice_id"] == "i1")
check("extract payment: unknown customer warns a new one will be created",
      any("isn't in your Zoho contacts" in w for w in ex["warnings"]))

inbox_books.extract_fields = lambda record_type, message: {
    "party_name": "OJAS ENTERPISES", "date": "2026-08-31", "total": 324941, "reference_number": "UTR-88",
    "related_invoice_numbers": ["26-27/016", "26-27/017"], "payment_mode": "banktransfer"}
r = client.post("/inbox-books/extract", json={"message_id": "m-vp-missing", "record_type": "vendor_payment"}, headers=headers)
ex = r.json()
cands = {c["bill_number"]: c for c in ex.get("bill_candidates", [])}
check("extract vendor payment: 200", r.status_code == 200)
check("extract vendor payment: the bills named in the email are offered and marked likely",
      cands.get("26-27/016", {}).get("best") and cands.get("26-27/017", {}).get("best"))
check("extract vendor payment: the supplier's other open bill is offered but not pre-ticked",
      cands.get("26-27/099", {}).get("best") is False)
check("extract vendor payment: another supplier's bill is not offered", "ACM-5555" not in cands)
check("extract vendor payment: no candidates for other record types",
      client.post("/inbox-books/extract", json={"message_id": "m-pay-missing", "record_type": "customer_payment"},
                  headers=headers).json()["bill_candidates"] == [])

# ---------- create: refused while the switch is off ----------
bill_fields = {"party_name": "Acme Supplies", "document_number": "INV-9001", "date": "2026-09-19",
               "due_date": "2026-10-19", "total": 11800, "account_id": "acc-exp", "notes": "Widgets order"}
r = client.post("/inbox-books/create", json={"message_id": "m-bill-missing", "record_type": "bill", "fields": bill_fields},
                headers=headers)
check("create: refused (403) while INBOX_BOOKS_WRITE is off", r.status_code == 403)
check("create: nothing posted while off", posted == [])

# ---------- turn the switch on ----------
inbox_books.settings.INBOX_BOOKS_WRITE = True
refreshed = []
connectors_zoho.run_full_sync = lambda tenant, connector, only=None: refreshed.append(only) or {}


def fake_post(api, tok, org, path, payload):
    posted.append((path, payload, org, api, tok))
    if path == "contacts":
        return {"contact": {"contact_id": "c-new"}}
    if path == "bills":
        return {"bill": {"bill_id": "zb1", "bill_number": payload["bill_number"]}}
    if path == "customerpayments":
        return {"payment": {"payment_id": "zp1", "payment_number": "PMT-9"}}
    if path == "estimates":
        return {"estimate": {"estimate_id": "ze1", "estimate_number": "EST-9"}}
    if path == "vendorpayments":
        return {"payment": {"payment_id": "zvp1", "payment_number": "VP-9"}}
    return {}


inbox_books._zoho_post = fake_post

def call_create(mid, rtype, fields, **extra):
    return client.post("/inbox-books/create", json={"message_id": mid, "record_type": rtype, "fields": fields, **extra},
                       headers=headers)

# an id that isn't one of THIS tenant's synced emails is refused
r = call_create("not-a-real-id", "bill", bill_fields)
check("create: email id not in this tenant's emails -> 404", r.status_code == 404)
r = call_create("../../users/me", "bill", bill_fields)
check("create: malformed email id -> 404", r.status_code == 404)
r = client.post("/inbox-books/extract", json={"message_id": "nope", "record_type": "bill"}, headers=headers)
check("extract: email id not in this tenant's emails -> 404", r.status_code == 404)
r = client.post("/inbox-books/dismiss", json={"message_id": "nope"}, headers=headers)
check("dismiss: email id not in this tenant's emails -> 404", r.status_code == 404)

# validation
r = call_create("m-bill-missing", "bill", {**bill_fields, "account_id": ""})
check("create bill: missing expense account -> 400", r.status_code == 400)
r = call_create("m-bill-missing", "bill", {**bill_fields, "document_number": ""})
check("create bill: missing bill number -> 400", r.status_code == 400)
r = call_create("m-bill-missing", "bill", {**bill_fields, "date": "not a date"})
check("create bill: bad date -> 400", r.status_code == 400)
r = call_create("m-bill-missing", "bill", {**bill_fields, "total": None})
check("create bill: no amount -> 400", r.status_code == 400)
check("validation failures posted nothing", posted == [])

# happy path, existing vendor
r = call_create("m-bill-missing", "bill", bill_fields)
check("create bill: 200", r.status_code == 200 and r.json().get("ok") is True)
check("create bill: posted to /bills exactly once, no contact created",
      [p[0] for p in posted] == ["bills"])
pl = posted[0][1]
check("create bill: payload uses the existing vendor, bill number, account and amount",
      pl["vendor_id"] == "c-acme" and pl["bill_number"] == "INV-9001" and pl["date"] == "2026-09-19"
      and pl["line_items"][0]["account_id"] == "acc-exp" and pl["line_items"][0]["rate"] == 11800.0
      and pl["due_date"] == "2026-10-19")
check("create bill: went to the tenant's Zoho org + domain with the tenant's token",
      posted[0][2] == "ORG1" and posted[0][3] == "https://www.zohoapis.in" and posted[0][4] == "z-acc")
check("create bill: Zoho tables refreshed afterwards", refreshed and refreshed[0] == ["bills", "customers"])

# second create for the same email is blocked
n = len(posted)
r = call_create("m-bill-missing", "bill", bill_fields)
check("create bill: second create for the same email -> 409", r.status_code == 409)
check("create bill: nothing more posted", len(posted) == n)
ids = {i["message_id"] for i in client.get("/inbox-books/missing", headers=headers).json()["items"]}
check("created email leaves the missing list", "m-bill-missing" not in ids)

# duplicate of something already in Zoho
r = call_create("m-dup", "bill", {**bill_fields, "document_number": "BT-77", "total": 5000, "party_name": "Beta Traders"})
check("create bill: matches an existing Zoho bill (reference) -> 409", r.status_code == 409)
check("create bill: nothing posted for the duplicate", len(posted) == n)
r = call_create("m-dup", "bill", {**bill_fields, "document_number": "BT-77", "total": 5000, "party_name": "Beta Traders"},
                allow_duplicate=True)
check("create bill: 'add anyway' goes through", r.status_code == 200)
check("create bill: new vendor was created first, then the bill",
      [p[0] for p in posted[n:]] == ["contacts", "bills"] and posted[n][1]["contact_type"] == "vendor"
      and posted[n + 1][1]["vendor_id"] == "c-new")

# customer payment
pay_fields = {"party_name": "HDFC Client", "date": "2026-09-18", "total": 25000, "reference_number": "UTR123",
              "deposit_account_id": "acc-bank", "invoice_id": "i1", "payment_mode": "banktransfer"}
r = call_create("m-pay-missing", "customer_payment", {**pay_fields, "deposit_account_id": ""})
check("create payment: missing deposit account -> 400", r.status_code == 400)
n = len(posted)
r = call_create("m-pay-missing", "customer_payment", pay_fields)
check("create payment: 200", r.status_code == 200)
pp = [p for p in posted[n:] if p[0] == "customerpayments"][0][1]
check("create payment: customer, amount, deposit account, invoice applied",
      pp["customer_id"] == "c-new" and pp["amount"] == 25000.0 and pp["account_id"] == "acc-bank"
      and pp["invoices"] == [{"invoice_id": "i1", "amount_applied": 25000.0}])
check("create payment: new contact typed customer",
      [p for p in posted[n:] if p[0] == "contacts"][0][1]["contact_type"] == "customer")

# vendor payment (money WE paid a supplier), spread over two bills
vp = {"party_name": "OJAS ENTERPISES", "date": _d(100), "total": 324941, "reference_number": "UTR-88",
      "paid_through_account_id": "acc-bank", "payment_mode": "banktransfer", "bill_ids": ["vb1", "vb2"]}
r = call_create("m-vp-missing", "vendor_payment", {**vp, "paid_through_account_id": ""})
check("create vendor payment: missing 'paid from' account -> 400", r.status_code == 400)
r = call_create("m-vp-missing", "vendor_payment", {**vp, "bill_ids": ["vb1", "../x"]})
check("create vendor payment: malformed bill id -> 400", r.status_code == 400)
r = call_create("m-vp-missing", "vendor_payment", {**vp, "bill_ids": ["vb1", "no-such-bill"]})
check("create vendor payment: bill not in synced Zoho data -> 409, nothing posted",
      r.status_code == 409 and not [p for p in posted if p[0] == "vendorpayments"])
n = len(posted)
refreshed.clear()
r = call_create("m-vp-missing", "vendor_payment", vp)
check("create vendor payment: 200", r.status_code == 200 and r.json().get("zoho_number") == "VP-9")
vpp = [p for p in posted[n:] if p[0] == "vendorpayments"][0][1]
check("create vendor payment: vendor, amount, paid-from account and reference",
      vpp["vendor_id"] == "c-new" and vpp["amount"] == 324941.0 and vpp["paid_through_account_id"] == "acc-bank"
      and vpp["reference_number"] == "UTR-88")
check("create vendor payment: applied to both bills, oldest first, each up to what it owes",
      vpp["bills"] == [{"bill_id": "vb1", "amount_applied": 100000.0}, {"bill_id": "vb2", "amount_applied": 224941.0}])
check("create vendor payment: contact typed vendor",
      [p for p in posted[n:] if p[0] == "contacts"][0][1]["contact_type"] == "vendor")
check("create vendor payment: payments AND bills refreshed afterwards (balances changed)",
      refreshed and refreshed[0] == ["vendor_payments", "bills", "customers"])
r = call_create("m-vp-inzoho", "vendor_payment", {**vp, "total": 150000, "reference_number": "", "date": _d(15)}, allow_duplicate=True)
vpp = [p for p in posted if p[0] == "vendorpayments"][-1][1]
check("create vendor payment: never applies more than the money paid (150000 over two bills)",
      r.status_code == 200 and sum(b["amount_applied"] for b in vpp["bills"]) == 150000.0)
r = call_create("m-body-missing", "vendor_payment", {**vp, "bill_ids": [], "total": 999.0, "reference_number": "U-1", "date": "2026-09-01"})
vpp = [p for p in posted if p[0] == "vendorpayments"][-1][1]
check("create vendor payment: no bills ticked -> recorded unapplied (no 'bills' key)", r.status_code == 200 and "bills" not in vpp)
r = call_create("m-body-fail", "vendor_payment", {**vp, "total": 324941.0, "date": _d(15), "reference_number": ""})
check("create vendor payment: matches an existing Zoho payment (amount + date) -> 409",
      r.status_code == 409 and "already has a matching" in r.json()["detail"])

# estimate + expense
r = call_create("m-quote-missing", "estimate", {"party_name": "Client One", "date": "2026-09-16", "total": 90000,
                                                "document_number": "Q-55"})
check("create estimate: 200 using existing customer",
      r.status_code == 200 and [p for p in posted if p[0] == "estimates"][-1][1]["customer_id"] == "c-cust")
r = call_create("m-exp", "expense", {"party_name": "Uber", "date": "2026-09-15", "total": 350})
check("create expense: needs both accounts -> 400", r.status_code == 400)

# Zoho says the token lacks write permission -> friendly reconnect message
def deny(api, tok, org, path, payload):
    raise inbox_books.InboxError(403, inbox_books._RECONNECT)


inbox_books._zoho_post = deny
r = call_create("m-noperm", "bill", {**bill_fields, "document_number": "ZZ-1", "total": 123, "party_name": "Acme Supplies"})
check("create: missing Zoho permission -> 403 with reconnect instructions",
      r.status_code == 403 and "reconnect" in r.json()["detail"].lower())

# --- money-safety checks ---
inbox_books._zoho_post = fake_post
n = len(posted)
lines = [{"description": "Widgets", "quantity": 2, "rate": 5000}]
r = call_create("m-mismatch", "bill", {**bill_fields, "document_number": "MM-1", "total": 11800, "line_items": lines})
check("create bill: lines (10000) vs document total (11800 incl. GST) -> 400, nothing posted",
      r.status_code == 400 and "add up" in r.json()["detail"] and len(posted) == n)
r = call_create("m-mismatch", "bill", {**bill_fields, "document_number": "MM-1", "total": 11800,
                                        "line_items": lines + [{"description": "GST 18%", "quantity": 1, "rate": 1800}]})
check("create bill: with the GST line added it matches and is booked at 11800",
      r.status_code == 200 and sum(li["rate"] * li["quantity"] for li in posted[-1][1]["line_items"]) == 11800)
r = call_create("m-usd", "bill", {**bill_fields, "document_number": "USD-1", "currency": "USD"})
check("create: non-INR document refused with a clear message", r.status_code == 400 and "USD" in r.json()["detail"])

# payment: cash amount is the TOTAL even if lines are present; amount_applied capped to invoice balance
n = len(posted)
r = call_create("m-pay2", "customer_payment", {"party_name": "Client One", "date": "2026-09-18", "total": 5000,
                                                "deposit_account_id": "acc-bank", "invoice_id": "i2",
                                                "line_items": [{"description": "x", "quantity": 1, "rate": 4237.29}]})
pp = [p for p in posted[n:] if p[0] == "customerpayments"][0][1]
check("payment: books the total received (5000), not the pre-tax line sum", r.status_code == 200 and pp["amount"] == 5000.0)
check("payment: amount_applied capped at the invoice balance (1000)", pp["invoices"][0]["amount_applied"] == 1000.0)

# live duplicate check for bills (synced copy may be stale)
live_state["bills"] = [{"bill_number": "LIVE-9", "vendor_name": "Acme Supplies"}]
n = len(posted)
r = call_create("m-live", "bill", {**bill_fields, "document_number": "LIVE-9"})
check("create bill: live Zoho lookup finds the bill the stale snapshot missed -> 409", r.status_code == 409 and len(posted) == n)
live_state["bills"] = []

# an existing contact found LIVE is reused instead of creating a duplicate contact
live_state["contacts"] = [{"contact_id": "c-live", "contact_name": "Brand New Vendor", "contact_type": "vendor", "status": "active"}]
n = len(posted)
r = call_create("m-live", "bill", {**bill_fields, "document_number": "LIVE-10", "party_name": "Brand New Vendor"})
check("create bill: contact found live is reused (no contact POST)",
      r.status_code == 200 and [p[0] for p in posted[n:]] == ["bills"] and posted[n][1]["vendor_id"] == "c-live")
live_state["contacts"] = []

# a definite Zoho rejection frees the claim so the user can fix the form and retry
def reject(api, tok, org, path, payload):
    raise inbox_books.InboxError(422, "Zoho rejected it: Please select a GST treatment")


inbox_books._zoho_post = reject
r = call_create("m-reject", "bill", {**bill_fields, "document_number": "RJ-1"})
check("create: Zoho rejection is shown to the user (422)", r.status_code == 422 and "GST" in r.json()["detail"])
inbox_books._zoho_post = fake_post
r = call_create("m-reject", "bill", {**bill_fields, "document_number": "RJ-1"})
check("create: retry after a definite rejection is allowed", r.status_code == 200)

# a timeout AFTER a write was sent is ambiguous: keep it blocked so nothing is double-booked
import requests as _rq  # noqa: E402


def timeout(api, tok, org, path, payload):
    if path == "contacts":
        return {"contact": {"contact_id": "c-t"}}
    raise _rq.Timeout("read timed out")


inbox_books._zoho_post = timeout
r = call_create("m-timeout", "bill", {**bill_fields, "document_number": "TO-1"})
check("create: timeout after sending -> 502 telling the user to check Zoho", r.status_code == 502 and "Check Zoho" in r.json()["detail"])
inbox_books._zoho_post = fake_post
n = len(posted)
r = call_create("m-timeout", "bill", {**bill_fields, "document_number": "TO-1"})
check("create: retry after an ambiguous timeout stays blocked (409), nothing posted", r.status_code == 409 and len(posted) == n)

# two racing requests: only one may claim the email
with inbox_books._db(tenant) as (eng, sch):
    inbox_books._reserve(eng, sch, "m-live", "estimate")
    try:
        inbox_books._reserve(eng, sch, "m-live", "estimate")
        raced = False
    except inbox_books.InboxError as e:
        raced = e.status == 409
check("race: second claim for the same email is refused (409)", raced)

# accounts for the review form
inbox_books._zoho_get = lambda api, tok, org, path, params=None: {"page_context": {"has_more_page": False}, "chartofaccounts": [
    {"account_id": "a1", "account_name": "Office Supplies", "account_type": "expense", "is_active": True},
    {"account_id": "a2", "account_name": "HDFC Current", "account_type": "bank", "is_active": True},
    {"account_id": "a3", "account_name": "Old", "account_type": "expense", "is_active": False},
    {"account_id": "a4", "account_name": "Sales", "account_type": "income", "is_active": True}]}
r = client.get("/inbox-books/accounts", headers=headers)
acc = r.json()
check("accounts: expense and bank split, inactive/income dropped",
      [a["account_id"] for a in acc["expense_accounts"]] == ["a1"] and [a["account_id"] for a in acc["bank_accounts"]] == ["a2"])

# ---------- tenant isolation: another tenant sees none of this ----------
r2 = client.post("/auth/register", json={"email": "other@example.com", "password": "pass123", "company": "Other Co", "location": ""})
h2 = {"Authorization": f"Bearer {r2.json()['token']}"}
check("other tenant: 400 (nothing connected), never sees this tenant's list",
      client.get("/inbox-books/missing", headers=h2).status_code == 400)

# ---------- Zoho consent scope only asks for write when switched on ----------
inbox_books.settings.INBOX_BOOKS_WRITE = False
config.get_settings().INBOX_BOOKS_WRITE = False
check("zoho scope: read-only while switch is off", "CREATE" not in connectors_zoho._oauth_scope())
config.get_settings().INBOX_BOOKS_WRITE = True
check("zoho scope: adds CREATE scopes when switch is on", "ZohoBooks.bills.CREATE" in connectors_zoho._oauth_scope())
check("zoho scope: includes vendor payments", "ZohoBooks.vendorpayments.CREATE" in connectors_zoho._oauth_scope())

print()
if fails:
    print(f"FAILED: {fails}")
    sys.exit(1)
print("ALL INBOX -> BOOKS TESTS PASSED")
