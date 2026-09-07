"""Ganak backend — multi-tenant ask-your-data API.

Each company (tenant) has its own database. A request is authenticated, the
caller's company is resolved, and the read-only NL->SQL pipeline runs against
THAT company's database only. The AI never sees another company's data.

Public:
  GET  /ping            liveness
  POST /auth/register   create a company + first user, returns a token
  POST /auth/login      returns a token
Authenticated (Bearer token):
  GET  /me              current user + company
  GET  /health          liveness + this company's DB connectivity
  GET  /schema          the table/column map the AI sees (this company)
  POST /ask             question -> read-only SQL -> answer + chart + rows
"""
import logging

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import get_settings
from . import db, llm, tenancy, auth, seed, docstore, docai, billing, zoho_live, connectors_routes, digest, digest_routes
from .guardrails import sanitize, UnsafeSQLError

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ganak")
settings = get_settings()


def _debit(tenant_id: int, kind: str, detail: str = ""):
    """Convert the tokens this request spent into rupees and debit the wallet."""
    cost = billing.request_cost_inr()
    bal = tenancy.get_balance(tenant_id)
    if cost > 0:
        bal = tenancy.adjust_balance(tenant_id, -cost)
        tenancy.record_ledger(tenant_id, kind, -cost, bal, detail)
    return bal, cost

app = FastAPI(title="Ganak API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(connectors_routes.router)
app.include_router(digest_routes.router)


@app.on_event("startup")
def _startup():
    seed.bootstrap()
    if settings.AUTH_SECRET in ("dev-only-change-me", ""):
        log.warning("GANAK_AUTH_SECRET is not strong \u2014 set it in backend/.env before production.")
    digest.start_scheduler()


# ---------------- models ----------------
class RegisterRequest(BaseModel):
    email: str
    password: str
    company: str
    location: str | None = ""


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    token: str
    email: str
    company: str
    location: str = ""
    dialect: str = "postgres"


class MeResponse(BaseModel):
    email: str
    company: str
    location: str = ""
    role: str = "owner"
    dialect: str = "postgres"
    balance_inr: float = 0


class AskRequest(BaseModel):
    question: str
    mode: str = "warehouse"  # "warehouse" (SQL) or "live" (Zoho Books API)


class ChartSpec(BaseModel):
    type: str = "none"
    x: str | None = None
    y: str | None = None


class AskResponse(BaseModel):
    answer: str
    sql: str
    columns: list
    rows: list
    chart: ChartSpec
    cost_inr: float = 0
    balance_inr: float | None = None


# ---------------- public ----------------
@app.get("/ping")
def ping():
    return {"service": "ganak", "ok": True}


def _auth_payload(user: dict, tenant: dict) -> AuthResponse:
    token = auth.make_token(user["id"], tenant["id"], user["email"])
    return AuthResponse(
        token=token,
        email=user["email"],
        company=tenant["name"],
        location=tenant.get("location") or "",
        dialect=db.dialect_of(tenant["db_url"]),
    )


@app.post("/auth/register", response_model=AuthResponse)
def register(req: RegisterRequest):
    email = (req.email or "").strip().lower()
    if "@" not in email or "." not in email:
        raise HTTPException(400, "Enter a valid email address.")
    if len(req.password or "") < 6:
        raise HTTPException(400, "Password must be at least 6 characters.")
    if not (req.company or "").strip():
        raise HTTPException(400, "Company name is required.")
    if tenancy.get_user_by_email(email):
        raise HTTPException(409, "That email is already registered. Try logging in.")

    # each new company gets its own fresh (empty) warehouse (a Postgres schema
    # in cloud mode, a standalone SQLite file locally)
    db_url, db_schema = seed.provision_tenant_db(req.company)
    tenant_id = tenancy.create_tenant(
        req.company.strip(), db_url, (req.location or "").strip(),
        settings.SIGNUP_BONUS_INR, db_schema,
    )
    user_id = tenancy.create_user(email, auth.hash_password(req.password), tenant_id, "owner")
    return _auth_payload(tenancy.get_user(user_id), tenancy.get_tenant(tenant_id))


@app.post("/auth/login", response_model=AuthResponse)
def login(req: LoginRequest):
    email = (req.email or "").strip().lower()
    auth.check_not_locked(email)
    user = tenancy.get_user_by_email(email)
    if not user or not auth.verify_password(req.password or "", user["pw_hash"]):
        auth.record_failed_login(email)
        raise HTTPException(401, "Wrong email or password.")
    auth.clear_failed_login(email)
    return _auth_payload(user, tenancy.get_tenant(user["tenant_id"]))


# ---------------- authenticated ----------------
@app.get("/me", response_model=MeResponse)
def me(ident: dict = Depends(auth.current_user)):
    u, t = ident["user"], ident["tenant"]
    return MeResponse(
        email=u["email"], company=t["name"], location=t.get("location") or "",
        role=u.get("role") or "owner", dialect=db.dialect_of(t["db_url"]),
        balance_inr=round(tenancy.get_balance(t["id"]), 2),
    )


@app.get("/health")
def health(ident: dict = Depends(auth.current_user)):
    t = ident["tenant"]
    return {
        "ok": True,
        "database": "up" if db.ping(t["db_url"], t.get("db_schema")) else "down",
        "company": t["name"],
    }


@app.get("/schema")
def schema(ident: dict = Depends(auth.current_user)):
    t = ident["tenant"]
    return {"schema": db.load_schema(t["db_url"], t.get("db_schema"), refresh=True)}


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest, ident: dict = Depends(auth.current_user)):
    q = (req.question or "").strip()
    if not q:
        raise HTTPException(400, "Question is empty.")
    if len(q) > 1000:
        raise HTTPException(400, "That question is too long \u2014 please shorten it.")
    tenant = ident["tenant"]
    tid = tenant["id"]
    if tenancy.get_balance(tid) <= 0:
        raise HTTPException(402, "Your balance is empty. Please recharge to keep using Ganak.")
    db_url = tenant["db_url"]
    db_schema = tenant.get("db_schema")
    dialect = db.dialect_of(db_url)
    live = (req.mode or "warehouse").lower() == "live"

    billing.reset_usage()
    _state = {}

    def settle():
        if "bal" not in _state:
            _state["bal"], _state["cost"] = _debit(tid, "ask-live" if live else "ask", q[:80])
        return _state["bal"], _state["cost"]

    try:
        if live:
            if not zoho_live.configured():
                raise HTTPException(400, "Live mode needs Zoho keys in backend/.env (ZOHO_REFRESH_TOKEN, ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_ORG_ID). Use Warehouse mode meanwhile.")
            route = llm.question_to_zoho(q)
            entity, rows = zoho_live.fetch(route.get("entity", "invoices"), route.get("params") or {})
            log.info("[tenant %s] LIVE Zoho %s -> %d rows", tid, entity, len(rows))
            narration = llm.narrate(q, rows)
            sql_display = f"[live] Zoho Books \u2192 {entity} ({len(rows)} records)"
            columns = list(rows[0].keys()) if rows else []
        else:
            schema = db.load_schema(db_url, db_schema)
            raw_sql = llm.question_to_sql(q, schema, dialect=dialect)
            sql_display = sanitize(raw_sql)
            log.info("[tenant %s] Q: %s | SQL: %s", tid, q, sql_display)
            columns, rows = db.run_select(db_url, sql_display, db_schema)
            if len(rows) == 1 and len(columns) == 1:
                col = columns[0]
                val = rows[0][col]
                money = any(k in col.lower() for k in
                            ("revenue", "amount", "total", "paid", "balance", "outstanding", "due", "expense", "sales", "payment"))
                label = col.replace("_", " ").strip().capitalize()
                try:
                    shown = f"{settings.CURRENCY}{float(val):,.2f}" if (money and val is not None) else str(val)
                except (TypeError, ValueError):
                    shown = str(val)
                narration = {"answer": f"{label}: {shown}", "chart": {"type": "none"}}
            else:
                narration = llm.narrate(q, rows)
        bal, cost = settle()
        return AskResponse(
            answer=narration.get("answer", ""),
            sql=sql_display, columns=columns, rows=rows,
            chart=ChartSpec(**(narration.get("chart") or {"type": "none"})),
            cost_inr=round(cost or 0, 2), balance_inr=round(bal or 0, 2),
        )
    except UnsafeSQLError as e:
        settle()
        log.info("Blocked non-SELECT/unsafe SQL: %s", e)
        raise HTTPException(
            400,
            "I can only answer questions about your business data. Try asking about "
            "revenue, expenses, invoices, payments, or who owes you money.",
        )
    except HTTPException:
        settle()
        raise
    except Exception as e:  # pragma: no cover
        settle()
        log.exception("ask failed")
        name = type(e).__name__
        text = str(e)
        if "zoho" in text.lower():
            msg = text
        elif "workspace-id is required" in text or "anthropic-workspace-id" in text:
            msg = "Your Anthropic key is workspace-linked. Add ANTHROPIC_WORKSPACE_ID=wrkspc_... to backend/.env, then restart."
        elif name in ("AuthenticationError", "PermissionDeniedError") or "401" in text or "Unauthorized" in text:
            msg = "AI key not accepted (401 Unauthorized). Create a fresh key at console.anthropic.com and paste the FULL key into backend/.env, then restart."
        elif name == "NotFoundError" or ("model" in text.lower() and "not" in text.lower()):
            msg = f"The AI model '{settings.MODEL}' was not found. Update MODEL in backend/.env to a current Claude model, then restart."
        elif name == "RateLimitError" or "credit balance" in text.lower() or "429" in text:
            msg = "AI request was rate-limited or the account is out of credit. Add credit at console.anthropic.com and retry."
        elif name in ("APIConnectionError", "APITimeoutError") or "connect" in text.lower():
            msg = "Could not reach the service. Check this PC's internet connection and retry."
        else:
            msg = "Could not answer that. Try rephrasing."
        raise HTTPException(500, msg) from e


# ---------------- documents: PDF -> structured fields -> warehouse ----------------
import base64 as _b64


class ExtractRequest(BaseModel):
    filename: str
    data_b64: str  # base64 of the PDF (no data: prefix)


class DocumentRecord(BaseModel):
    doc_type: str | None = None
    party: str | None = None
    doc_date: str | None = None
    amount: float | None = None
    currency: str | None = "INR"
    reference_no: str | None = None
    gst_no: str | None = None
    direction: str | None = None
    summary: str | None = None
    source_filename: str | None = None
    raw: dict | None = None


@app.post("/documents/extract")
def documents_extract(req: ExtractRequest, ident: dict = Depends(auth.current_user)):
    if not (req.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "Please choose a PDF file.")
    try:
        data = _b64.b64decode(req.data_b64, validate=False)
    except Exception:
        raise HTTPException(400, "That file could not be read.")
    if not data:
        raise HTTPException(400, "The file is empty.")
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(400, "PDF is too large (max 8 MB). Try a smaller file.")
    tid = ident["tenant"]["id"]
    if tenancy.get_balance(tid) <= 0:
        raise HTTPException(402, "Your balance is empty. Please recharge to read documents.")
    billing.reset_usage()
    try:
        fields = docai.extract_from_pdf(data)
    except Exception as e:  # pragma: no cover
        _debit(tid, "document", req.filename)
        log.exception("pdf extract failed")
        name = type(e).__name__
        text = str(e)
        if name in ("AuthenticationError",) or "401" in text or "Unauthorized" in text:
            raise HTTPException(500, "AI key not accepted. Check backend/.env, then restart.")
        raise HTTPException(500, "Couldn't read that PDF — try a clearer copy or a different file.")
    _debit(tid, "document", req.filename)
    fields["source_filename"] = req.filename
    return fields


@app.post("/documents/load")
def documents_load(rec: DocumentRecord, ident: dict = Depends(auth.current_user)):
    t = ident["tenant"]
    db_url, db_schema = t["db_url"], t.get("db_schema")
    try:
        docstore.insert_document(db_url, rec.model_dump(), db_schema)
        db.invalidate_schema(db_url, db_schema)  # so Ask can query `documents` right away
    except Exception as e:  # pragma: no cover
        log.exception("document load failed")
        raise HTTPException(500, "Couldn't save the document to your warehouse.")
    return {"ok": True, "message": "Saved. You can now ask Ganak about it."}


# ---------------- billing: prepaid wallet ----------------
class RechargeRequest(BaseModel):
    amount_inr: float


@app.get("/billing")
def billing_status(ident: dict = Depends(auth.current_user)):
    tid = ident["tenant"]["id"]
    return {
        "balance_inr": round(tenancy.get_balance(tid), 2),
        "currency": settings.CURRENCY,
        "ledger": tenancy.recent_ledger(tid),
    }


@app.post("/billing/recharge")
def billing_recharge(req: RechargeRequest, ident: dict = Depends(auth.current_user)):
    # NOTE: dev/simulated top-up. In production a payment provider (e.g. Razorpay)
    # verifies the payment, then its webhook calls this to credit the wallet.
    amt = float(req.amount_inr or 0)
    if amt <= 0 or amt > 100000:
        raise HTTPException(400, "Enter an amount between 1 and 100000.")
    tid = ident["tenant"]["id"]
    bal = tenancy.adjust_balance(tid, amt)
    tenancy.record_ledger(tid, "recharge", amt, bal, "wallet top-up")
    return {"ok": True, "balance_inr": round(bal, 2)}
