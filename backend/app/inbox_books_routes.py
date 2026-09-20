"""Inbox -> Books API (see inbox_books.py for what each step does).

  GET  /inbox-books/status     what is connected / switched on (free)
  GET  /inbox-books/missing    recent finance emails with no matching Zoho record (free, read-only)
  POST /inbox-books/extract    read ONE email with AI and propose the Zoho fields (charged, no write)
  GET  /inbox-books/accounts   the tenant's Zoho expense / bank accounts for the review form (free)
  POST /inbox-books/create     add ONE reviewed record to Zoho Books (only when INBOX_BOOKS_WRITE=1)
  POST /inbox-books/dismiss    hide an email from the list ("not a Zoho record")
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .config import get_settings
from . import auth, billing, tenancy, inbox_books
from .inbox_books import InboxError

log = logging.getLogger("ganak.inbox_books")
settings = get_settings()
router = APIRouter(prefix="/inbox-books", tags=["inbox-books"])


class ExtractIn(BaseModel):
    message_id: str
    record_type: str


class CreateIn(BaseModel):
    message_id: str
    record_type: str
    fields: dict
    allow_duplicate: bool = False


class DismissIn(BaseModel):
    message_id: str


def _connectors(tenant_id: int, need_gmail=True, need_zoho=True):
    gmail = tenancy.get_connector(tenant_id, "gmail")
    zoho = tenancy.get_connector(tenant_id, "zoho")
    if need_gmail and not gmail:
        raise HTTPException(400, "Connect Gmail on the Sources page first.")
    if need_zoho and not zoho:
        raise HTTPException(400, "Connect Zoho Books on the Sources page first.")
    return gmail, zoho


def _wrap(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except InboxError as e:
        raise HTTPException(e.status, e.message)


@router.get("/status")
def status(ident: dict = Depends(auth.current_user)):
    tid = ident["tenant"]["id"]
    return {
        "gmail_connected": bool(tenancy.get_connector(tid, "gmail")),
        "zoho_connected": bool(tenancy.get_connector(tid, "zoho")),
        "write_enabled": settings.INBOX_BOOKS_WRITE,
    }


@router.get("/missing")
def missing(days: int = 30, ident: dict = Depends(auth.current_user)):
    tenant = ident["tenant"]
    _connectors(tenant["id"])
    return _wrap(inbox_books.find_missing, tenant, days=days)


@router.post("/extract")
def extract(req: ExtractIn, ident: dict = Depends(auth.current_user)):
    tenant = ident["tenant"]
    tid = tenant["id"]
    gmail, _zoho = _connectors(tid, need_zoho=False)
    if tenancy.get_balance(tid) <= 0:
        raise HTTPException(402, "Your balance is empty. Please recharge to read emails.")
    billing.reset_usage()
    try:
        return _wrap(inbox_books.extract, tenant, gmail, req.record_type, req.message_id)
    except HTTPException:
        raise
    except Exception as e:  # pragma: no cover
        log.exception("inbox extract failed")
        raise HTTPException(500, "Couldn't read that email - try again, or add it in Zoho by hand.") from e
    finally:
        from .main import _debit  # late import: main imports this module
        try:
            _debit(tid, "inbox-extract", req.message_id[:40])
        except Exception:  # pragma: no cover
            log.exception("inbox extract debit failed")


@router.get("/accounts")
def accounts(ident: dict = Depends(auth.current_user)):
    _gmail, zoho = _connectors(ident["tenant"]["id"], need_gmail=False)
    try:
        return _wrap(inbox_books.list_accounts, zoho)
    except HTTPException:
        raise
    except Exception as e:  # pragma: no cover
        log.exception("inbox accounts failed")
        raise HTTPException(502, "Couldn't load your Zoho accounts - try again.") from e


@router.post("/create")
def create(req: CreateIn, ident: dict = Depends(auth.current_user)):
    tenant = ident["tenant"]
    _gmail, zoho = _connectors(tenant["id"], need_gmail=False)
    try:
        return _wrap(inbox_books.create, tenant, zoho, req.record_type, req.message_id, req.fields,
                     allow_duplicate=req.allow_duplicate)
    except HTTPException:
        raise
    except Exception as e:  # pragma: no cover
        log.exception("inbox create failed")
        raise HTTPException(500, "Something went wrong while adding that. Please check Zoho Books before trying again.") from e


@router.post("/dismiss")
def dismiss(req: DismissIn, ident: dict = Depends(auth.current_user)):
    _wrap(inbox_books.dismiss, ident["tenant"], req.message_id)
    return {"ok": True}
