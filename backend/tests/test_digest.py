"""Smoke test for scheduled email digests -- no real SMTP or AI calls
involved (llm + digest.send_email are monkeypatched). Confirms: settings
save/validate correctly, send-now is gated on configured/recipients/balance,
a successful send is logged, a failed send is logged as an error without
crashing, and the scheduler's due-check (_is_due) + run_due_digests() only
fire once per period.
"""
import os
import sys
import pathlib
import time
from datetime import datetime, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

os.environ["GANAK_SKIP_DOTENV"] = "1"
os.environ["SEED_DEMO"] = "0"
os.environ["CONTROL_DB_PATH"] = "/tmp/ganak_control_digest_test.db"
os.environ["TENANTS_DIR"] = "/tmp/ganak_tenants_digest_test"
os.environ["DATABASE_URL"] = "sqlite:////tmp/ganak_demo_digest_test.db"
os.environ["SMTP_HOST"] = "smtp.example.com"
os.environ["SMTP_FROM"] = "ganak@example.com"

for f in ("/tmp/ganak_control_digest_test.db",):
    try:
        os.remove(f)
    except FileNotFoundError:
        pass

from fastapi.testclient import TestClient  # noqa: E402
from app import tenancy, seed, digest, billing, llm  # noqa: E402
from app.main import app  # noqa: E402

# Never touch a real AI provider or a real SMTP server in this test.
def fake_question_to_sql(q, schema, dialect="postgres"):
    billing.add_usage("claude-haiku-4-5-20251001", 200, 100)
    return "SELECT 1 AS n"

def fake_narrate(q, rows):
    return {"answer": "₹12,345.00", "chart": {"type": "none"}}

llm.question_to_sql = fake_question_to_sql
llm.narrate = fake_narrate

sent_emails = []

def fake_send_email(to_list, subject, html, text):
    sent_emails.append({"to": to_list, "subject": subject})

digest.send_email = fake_send_email

seed.bootstrap()
client = TestClient(app)
fails = []


def check(name, cond):
    print(("PASS" if cond else "FAIL") + " - " + name)
    if not cond:
        fails.append(name)


# ---------------- settings API ----------------
r = client.post("/auth/register", json={
    "email": "digesttest@example.com", "password": "pass123",
    "company": "Digest Test Co", "location": "",
})
check("register succeeds", r.status_code == 200)
token = r.json()["token"]
headers = {"Authorization": f"Bearer {token}"}
tenant_row = tenancy.get_user_by_email("digesttest@example.com")
tenant_id = tenant_row["tenant_id"]

r = client.get("/digest", headers=headers)
check("get settings 200", r.status_code == 200)
data = r.json()
check("configured (SMTP env set)", data["configured"] is True)
check("disabled by default", data["enabled"] is False)
check("weekly by default", data["frequency"] == "weekly")

r = client.post("/digest", headers=headers, json={"enabled": True, "frequency": "weekly", "weekday": 2, "hour": 9, "recipients": []})
check("enabling with no recipients is rejected (400)", r.status_code == 400)

r = client.post("/digest", headers=headers, json={
    "enabled": True, "frequency": "daily", "weekday": 0, "hour": 7,
    "recipients": ["Owner@DigestTest.com", "owner@digesttest.com", "not-an-email"],
})
check("save settings 200", r.status_code == 200)
saved = r.json()
check("recipients lowercased + de-duped + bad address dropped", saved["recipients"] == ["owner@digesttest.com"])
check("frequency saved", saved["frequency"] == "daily")
check("hour saved", saved["hour"] == 7)

r = client.get("/digest", headers=headers)
check("settings persisted across GET", r.json()["recipients"] == ["owner@digesttest.com"])

# ---------------- send-now ----------------
bal_before = tenancy.get_balance(tenant_id)
check("tenant starts with a positive balance", bal_before > 0)

r = client.post("/digest/send-now", headers=headers)
check("send-now accepted", r.status_code == 200 and r.json()["status"] == "sending")
check("email actually sent (background task ran)", len(sent_emails) == 1)
if sent_emails:
    check("sent to the saved recipient", sent_emails[0]["to"] == ["owner@digesttest.com"])
    check("subject mentions the company", "Digest Test Co" in sent_emails[0]["subject"])

log = tenancy.recent_digest_log(tenant_id)
check("a 'sent' log entry was recorded", any(l["status"] == "sent" for l in log))

bal_after = tenancy.get_balance(tenant_id)
check("wallet was debited for the AI usage", bal_after < bal_before)

# a failing send is logged as an error, not silently dropped or crashed
def failing_send_email(to_list, subject, html, text):
    raise RuntimeError("smtp connection refused")

digest.send_email = failing_send_email
sent_emails.clear()
r = client.post("/digest/send-now", headers=headers)
check("send-now still accepted even though the send will fail", r.status_code == 200)
log = tenancy.recent_digest_log(tenant_id)
check("the failure was logged as an error", log[0]["status"] == "error" and "smtp connection refused" in log[0]["detail"])
digest.send_email = fake_send_email

# balance gating: drain the wallet, confirm send-now is blocked (402)
tenancy.adjust_balance(tenant_id, -tenancy.get_balance(tenant_id))
r = client.post("/digest/send-now", headers=headers)
check("send-now blocked when balance is empty (402)", r.status_code == 402)
tenancy.adjust_balance(tenant_id, 100)  # restore for the scheduler tests below

# ---------------- _is_due ----------------
# A fixed reference time (not datetime.now()) so these checks never depend
# on what time it happens to be when the test runs. 2026-09-09 is a Wednesday
# (weekday() == 2), 14:30 IST.
IST = digest.IST
now = datetime(2026, 9, 9, 14, 30, tzinfo=IST)
check("sanity: reference date is a Wednesday", now.weekday() == 2)

due_daily = {"enabled": True, "frequency": "daily", "hour": 9, "weekday": 0, "last_sent_at": 0}
check("_is_due: daily, hour has passed, never sent -> due", digest._is_due(due_daily, now))

not_due_hour = {"enabled": True, "frequency": "daily", "hour": 18, "weekday": 0, "last_sent_at": 0}
check("_is_due: daily, hour hasn't arrived yet -> not due", not digest._is_due(not_due_hour, now))

already_today = {"enabled": True, "frequency": "daily", "hour": 9, "weekday": 0, "last_sent_at": now.timestamp()}
check("_is_due: already sent today -> not due again", not digest._is_due(already_today, now))

disabled = {"enabled": False, "frequency": "daily", "hour": 9, "weekday": 0, "last_sent_at": 0}
check("_is_due: disabled -> never due", not digest._is_due(disabled, now))

weekly_right_day = {"enabled": True, "frequency": "weekly", "hour": 9, "weekday": 2, "last_sent_at": 0}
check("_is_due: weekly, correct weekday + hour passed -> due", digest._is_due(weekly_right_day, now))

weekly_wrong_day = {"enabled": True, "frequency": "weekly", "hour": 9, "weekday": 3, "last_sent_at": 0}
check("_is_due: weekly, wrong weekday -> not due", not digest._is_due(weekly_wrong_day, now))

# ---------------- run_due_digests end-to-end ----------------
# Real time here (not the fixed `now` above) since run_due_digests calls
# datetime.now(IST) internally -- give it an hour that has definitely passed.
this_hour_ist = datetime.now(IST).hour
tenancy.upsert_digest_settings(tenant_id, True, "daily", 0, max(this_hour_ist - 1, 0), "owner@digesttest.com")
sent_emails.clear()
digest.run_due_digests()
check("run_due_digests sent the due tenant's digest", len(sent_emails) == 1)
row = tenancy.get_digest_settings(tenant_id)
check("last_sent_at was updated", row["last_sent_at"] > 0)

sent_emails.clear()
digest.run_due_digests()
check("run_due_digests does not resend the same tenant again today", len(sent_emails) == 0)

print()
if fails:
    print(f"FAILED: {fails}")
    sys.exit(1)
print("ALL DIGEST TESTS PASSED")
