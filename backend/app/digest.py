"""Scheduled email digests: a periodic (daily/weekly) plain-English summary of
the tenant's numbers -- paid revenue, outstanding receivables, expenses,
invoice volume, and the single biggest receivable -- assembled through the
same question -> SQL -> narrate pipeline as /ask, then emailed via SMTP.

Not tied to any one email provider: any SMTP account works (Gmail with an
app password, Outlook, or an SMTP relay from SendGrid/Mailgun/etc -- see the
SMTP_* settings in backend/.env). A tenant's own "Connect Gmail" (read-only
gmail.readonly scope, used only for finance-email classification) is
unrelated and can't send mail -- digests always go out from Ganak's own SMTP
identity, to whatever recipients the tenant lists.

A lightweight background thread (start_scheduler, started once from
main.py's startup hook) wakes every DIGEST_CHECK_INTERVAL_SECONDS and calls
run_due_digests(), which finds every tenant whose schedule is due (in IST)
and hasn't already been sent today, builds their digest, and emails it.
"""
import logging
import re
import smtplib
import threading
import time
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .config import get_settings
from . import billing, db, llm, tenancy
from .guardrails import sanitize

log = logging.getLogger("ganak.digest")
settings = get_settings()

IST = timezone(timedelta(hours=5, minutes=30))

# (label, question template) -- {days} is filled in per-send (1 for daily, 7 for weekly)
QUESTIONS = [
    ("Paid revenue", "What is my total paid invoice revenue in the last {days} days? Return a single total."),
    ("Outstanding receivables", "What is my total outstanding balance on unpaid or overdue invoices right now? Return a single total."),
    ("Expenses", "What were my total expenses in the last {days} days? Return a single total."),
    ("Invoices raised", "How many invoices were created in the last {days} days? Return a single count."),
    ("Biggest receivable", "Which single customer currently owes me the most money? Name the customer and the amount, top 1 only."),
]

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def configured() -> bool:
    return bool(settings.SMTP_HOST and settings.SMTP_FROM)


def _debit(tenant_id: int, detail: str) -> float:
    cost = billing.request_cost_inr()
    if cost > 0:
        bal = tenancy.adjust_balance(tenant_id, -cost)
        tenancy.record_ledger(tenant_id, "digest", -cost, bal, detail)
    return cost


def _headline(answer: str) -> str:
    m = re.search(r"₹[\d,.]+\s?(?:lakh|crore|L|Cr|k)?|\b\d[\d,]*(?:\.\d+)?%?", answer or "", re.I)
    if m:
        return m.group(0)
    a = answer or ""
    return a[:60] + "…" if len(a) > 60 else (a or "—")


def _gather_kpis(tenant: dict, days: int) -> list[dict]:
    """Run each digest question through the same NL->SQL->narrate pipeline /ask
    uses, and return [{label, value, detail}]. A single failed question shows
    as unavailable rather than failing the whole digest."""
    db_url, db_schema = tenant["db_url"], tenant.get("db_schema")
    dialect = db.dialect_of(db_url)
    schema_text = db.load_schema(db_url, db_schema)
    out = []
    for label, tmpl in QUESTIONS:
        q = tmpl.format(days=days)
        try:
            raw_sql = llm.question_to_sql(q, schema_text, dialect=dialect)
            sql = sanitize(raw_sql)
            _, rows = db.run_select(db_url, sql, db_schema)
            narration = llm.narrate(q, rows)
            answer = narration.get("answer", "")
            out.append({"label": label, "value": _headline(answer), "detail": answer})
        except Exception as e:  # pragma: no cover
            log.warning("digest KPI failed tenant=%s q=%r: %s", tenant.get("id"), q, e)
            out.append({"label": label, "value": "—", "detail": "unavailable this time"})
    return out


def _days_for(frequency: str) -> int:
    return 1 if frequency == "daily" else 7


def _period_label(frequency: str) -> str:
    return "the last 24 hours" if frequency == "daily" else "the last 7 days"


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _render_html(company: str, frequency: str, when: str, kpis: list[dict]) -> str:
    app_url = settings.PUBLIC_APP_BASE_URL.rstrip("/")
    period = _period_label(frequency)
    freq_word = "Daily" if frequency == "daily" else "Weekly"
    # Table-based layout (email-client safe) that collapses each KPI row to
    # a single stacked block below 480px -- readable full-width on an
    # iPhone/Android mail client without any horizontal scrolling or pinch-zoom.
    rows_html = "\n".join(
        f'''<tr class="kpi-row">
              <td class="kpi-cell" style="padding:14px 20px;border-bottom:1px solid #DDE4EC;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                  <tr>
                    <td style="font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:13px;color:#566a7d;padding-bottom:4px;">{_esc(k["label"])}</td>
                  </tr>
                  <tr>
                    <td style="font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:22px;font-weight:700;color:#11212F;">{_esc(k["value"])}</td>
                  </tr>
                </table>
              </td>
            </tr>'''
        for k in kpis
    )
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>{_esc(company)} — Ganak {freq_word} Digest</title>
</head>
<body style="margin:0;padding:0;background:#EEF2F6;-webkit-text-size-adjust:100%;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#EEF2F6;">
    <tr>
      <td align="center" style="padding:20px 12px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;width:100%;background:#FFFFFF;border-radius:14px;overflow:hidden;border:1px solid #DDE4EC;">
          <tr>
            <td style="background:linear-gradient(135deg,#0E7C6B,#0a5a4e);padding:22px 20px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td style="font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#ffffff;font-size:18px;font-weight:700;">Ganak</td>
                  <td align="right" style="font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#DCEDE9;font-size:12px;">{freq_word} Digest</td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:20px 20px 4px;">
              <p style="margin:0;font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:15px;color:#11212F;">
                <b>{_esc(company)}</b> — here's how things look over {period}, as of {_esc(when)} IST.
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:8px 0 4px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                {rows_html}
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:18px 20px 22px;" align="center">
              <a href="{app_url}/ask" style="display:inline-block;background:#0E7C6B;color:#ffffff;text-decoration:none;font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-weight:600;font-size:15px;padding:13px 26px;border-radius:10px;min-width:180px;">Open Ganak</a>
            </td>
          </tr>
          <tr>
            <td style="padding:16px 20px;background:#F3F6F9;border-top:1px solid #DDE4EC;">
              <p style="margin:0;font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:12px;line-height:1.6;color:#8395a6;">
                You're getting this because email digests are turned on for {_esc(company)} on Ganak.
                Manage frequency, day/time and recipients any time under
                <a href="{app_url}/digests" style="color:#0a5a4e;">Email Digests</a> in the app.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _render_text(company: str, frequency: str, when: str, kpis: list[dict]) -> str:
    freq_word = "Daily" if frequency == "daily" else "Weekly"
    period = _period_label(frequency)
    lines = [
        f"Ganak {freq_word} Digest — {company}",
        f"As of {when} IST, over {period}:",
        "",
    ]
    for k in kpis:
        lines.append(f"- {k['label']}: {k['value']}")
    lines += [
        "",
        f"Open Ganak: {settings.PUBLIC_APP_BASE_URL.rstrip('/')}/ask",
        "",
        f"Manage this digest: {settings.PUBLIC_APP_BASE_URL.rstrip('/')}/digests",
    ]
    return "\n".join(lines)


def build_digest(tenant: dict, frequency: str) -> dict:
    """Gather KPIs (billing the AI usage once for the whole batch, same as
    /ask), then render subject/html/text. Returns the built content plus
    what it cost so callers can decide whether to actually send it."""
    days = _days_for(frequency)
    billing.reset_usage()
    kpis = _gather_kpis(tenant, days)
    cost = _debit(tenant["id"], f"{frequency} digest")
    company = tenant["name"]
    when = datetime.now(IST).strftime("%d %b %Y, %I:%M %p")
    freq_word = "Daily" if frequency == "daily" else "Weekly"
    subject = f"Ganak {freq_word} Digest — {company} — {datetime.now(IST).strftime('%d %b %Y')}"
    return {
        "subject": subject,
        "html": _render_html(company, frequency, when, kpis),
        "text": _render_text(company, frequency, when, kpis),
        "cost_inr": cost,
        "kpis": kpis,
    }


def send_email(to_list: list[str], subject: str, html: str, text: str) -> None:
    if not configured():
        raise RuntimeError(
            "Email isn't configured on this server yet (set SMTP_HOST/SMTP_FROM in backend/.env)."
        )
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM
    msg["To"] = ", ".join(to_list)
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as server:
        if settings.SMTP_USE_TLS:
            server.starttls()
        if settings.SMTP_USER:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.sendmail(settings.SMTP_FROM, to_list, msg.as_string())


def send_now(tenant: dict, frequency: str, recipients: list[str]) -> dict:
    """Build + send one digest right now, logging the outcome either way."""
    digest = build_digest(tenant, frequency)
    try:
        send_email(recipients, digest["subject"], digest["html"], digest["text"])
    except Exception as e:
        tenancy.record_digest_log(tenant["id"], "error", str(e)[:300], ",".join(recipients))
        raise
    tenancy.record_digest_log(tenant["id"], "sent", digest["subject"], ",".join(recipients))
    return digest


# ---------------- scheduler ----------------
def _is_due(row: dict, now_ist: datetime) -> bool:
    if not row.get("enabled"):
        return False
    last_sent = row.get("last_sent_at") or 0
    if last_sent:
        last_date = datetime.fromtimestamp(last_sent, IST).date()
        if last_date == now_ist.date():
            return False  # already sent today -- don't resend on every tick
    hour = int(row.get("hour") if row.get("hour") is not None else 8)
    if now_ist.hour < hour:
        return False
    freq = row.get("frequency") or "weekly"
    if freq == "daily":
        return True
    weekday = int(row.get("weekday") if row.get("weekday") is not None else 0)
    return now_ist.weekday() == weekday


def run_due_digests() -> None:
    for row in tenancy.list_digest_settings():
        tenant_id = row.get("tenant_id")
        try:
            now_ist = datetime.now(IST)
            if not _is_due(row, now_ist):
                continue
            recipients = [e.strip() for e in (row.get("recipients") or "").split(",") if e.strip()]
            if not recipients:
                continue
            tenant = tenancy.get_tenant(tenant_id)
            if not tenant:
                continue
            if tenancy.get_balance(tenant_id) <= 0:
                tenancy.record_digest_log(
                    tenant_id, "error",
                    "Wallet balance is empty — this digest was skipped. Recharge to resume.",
                    ",".join(recipients),
                )
                tenancy.mark_digest_sent(tenant_id)  # try again next scheduled period, not every tick
                continue
            send_now(tenant, row.get("frequency") or "weekly", recipients)
            tenancy.mark_digest_sent(tenant_id)
            log.info("digest sent tenant=%s frequency=%s", tenant_id, row.get("frequency"))
        except Exception:  # pragma: no cover
            log.exception("digest run failed for tenant %s", tenant_id)


_scheduler_started = False
_scheduler_lock = threading.Lock()


def start_scheduler() -> None:
    """Idempotent: safe to call from startup even if it somehow runs twice."""
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return
        _scheduler_started = True

    def _loop():
        interval = max(60, settings.DIGEST_CHECK_INTERVAL_SECONDS)
        while True:
            try:
                run_due_digests()
            except Exception:  # pragma: no cover
                log.exception("digest scheduler tick failed")
            time.sleep(interval)

    threading.Thread(target=_loop, daemon=True, name="ganak-digest-scheduler").start()
    log.info("digest scheduler started (checking every %ss)", settings.DIGEST_CHECK_INTERVAL_SECONDS)
