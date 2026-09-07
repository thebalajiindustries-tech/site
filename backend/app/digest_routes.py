"""Scheduled digest settings + on-demand test send.

  GET  /digest             this tenant's settings + recent send log
  POST /digest              update settings (enable/disable, frequency, day, hour, recipients)
  POST /digest/send-now      build + send one right now (BackgroundTask), for testing

Sending (whether scheduled or "send now") runs in the background so the HTTP
response comes back immediately -- the frontend polls GET /digest to see the
new log entry land, the same pattern /connectors uses for a sync.
"""
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from . import auth, digest, tenancy

log = logging.getLogger("ganak.digest_routes")
router = APIRouter(prefix="/digest", tags=["digest"])


class DigestSettingsIn(BaseModel):
    enabled: bool = False
    frequency: str = "weekly"   # "daily" | "weekly"
    weekday: int = 0            # 0=Mon .. 6=Sun, used when frequency == "weekly"
    hour: int = 8               # 0-23, IST
    recipients: list[str] = Field(default_factory=list)


class DigestLogEntry(BaseModel):
    ts: float
    status: str
    detail: str
    recipients: str


class DigestSettingsOut(BaseModel):
    configured: bool
    enabled: bool = False
    frequency: str = "weekly"
    weekday: int = 0
    hour: int = 8
    recipients: list[str] = []
    last_sent_at: float = 0
    log: list[DigestLogEntry] = []


def _out(tenant_id: int) -> DigestSettingsOut:
    row = tenancy.get_digest_settings(tenant_id) or {}
    recips = [e.strip() for e in (row.get("recipients") or "").split(",") if e.strip()]
    return DigestSettingsOut(
        configured=digest.configured(),
        enabled=bool(row.get("enabled")),
        frequency=row.get("frequency") or "weekly",
        weekday=int(row.get("weekday") if row.get("weekday") is not None else 0),
        hour=int(row.get("hour") if row.get("hour") is not None else 8),
        recipients=recips,
        last_sent_at=row.get("last_sent_at") or 0,
        log=tenancy.recent_digest_log(tenant_id),
    )


@router.get("", response_model=DigestSettingsOut)
def get_settings_(ident: dict = Depends(auth.current_user)):
    return _out(ident["tenant"]["id"])


@router.post("", response_model=DigestSettingsOut)
def save_settings(req: DigestSettingsIn, ident: dict = Depends(auth.current_user)):
    tenant_id = ident["tenant"]["id"]
    freq = req.frequency if req.frequency in ("daily", "weekly") else "weekly"
    weekday = min(max(req.weekday, 0), 6)
    hour = min(max(req.hour, 0), 23)
    emails: list[str] = []
    for e in req.recipients:
        e = (e or "").strip().lower()
        if e and "@" in e and "." in e.split("@")[-1] and e not in emails:
            emails.append(e)
    if req.enabled and not emails:
        raise HTTPException(400, "Add at least one recipient email to turn digests on.")
    if len(emails) > 10:
        raise HTTPException(400, "Please keep it to 10 recipients or fewer.")
    tenancy.upsert_digest_settings(tenant_id, req.enabled, freq, weekday, hour, ",".join(emails))
    return _out(tenant_id)


def _send_and_log(tenant: dict, frequency: str, recipients: list[str]) -> None:
    try:
        digest.send_now(tenant, frequency, recipients)
    except Exception as e:
        log.error(f"digest send-now failed tenant={tenant['id']}: {e}")


@router.post("/send-now")
def send_now(background: BackgroundTasks, ident: dict = Depends(auth.current_user)):
    if not digest.configured():
        raise HTTPException(503, "Email isn't configured on this server yet (SMTP_HOST/SMTP_FROM in backend/.env).")
    tenant = ident["tenant"]
    row = tenancy.get_digest_settings(tenant["id"]) or {}
    recipients = [e.strip() for e in (row.get("recipients") or "").split(",") if e.strip()]
    if not recipients:
        raise HTTPException(400, "Add at least one recipient email first, then send a test.")
    if tenancy.get_balance(tenant["id"]) <= 0:
        raise HTTPException(402, "Your balance is empty. Please recharge to send a digest.")
    frequency = row.get("frequency") or "weekly"
    background.add_task(_send_and_log, tenant, frequency, recipients)
    return {"status": "sending"}
