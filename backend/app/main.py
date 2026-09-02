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
from . import db, llm, tenancy, auth, seed
from .guardrails import sanitize, UnsafeSQLError

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ganak")
settings = get_settings()

app = FastAPI(title="Ganak API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup():
    seed.bootstrap()


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


class AskRequest(BaseModel):
    question: str


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

    # each new company gets its own fresh (empty) warehouse
    db_url = seed.provision_tenant_db(req.company)
    tenant_id = tenancy.create_tenant(req.company.strip(), db_url, (req.location or "").strip())
    user_id = tenancy.create_user(email, auth.hash_password(req.password), tenant_id, "owner")
    return _auth_payload(tenancy.get_user(user_id), tenancy.get_tenant(tenant_id))


@app.post("/auth/login", response_model=AuthResponse)
def login(req: LoginRequest):
    user = tenancy.get_user_by_email((req.email or "").strip().lower())
    if not user or not auth.verify_password(req.password or "", user["pw_hash"]):
        raise HTTPException(401, "Wrong email or password.")
    return _auth_payload(user, tenancy.get_tenant(user["tenant_id"]))


# ---------------- authenticated ----------------
@app.get("/me", response_model=MeResponse)
def me(ident: dict = Depends(auth.current_user)):
    u, t = ident["user"], ident["tenant"]
    return MeResponse(
        email=u["email"], company=t["name"], location=t.get("location") or "",
        role=u.get("role") or "owner", dialect=db.dialect_of(t["db_url"]),
    )


@app.get("/health")
def health(ident: dict = Depends(auth.current_user)):
    db_url = ident["tenant"]["db_url"]
    return {
        "ok": True,
        "database": "up" if db.ping(db_url) else "down",
        "company": ident["tenant"]["name"],
    }


@app.get("/schema")
def schema(ident: dict = Depends(auth.current_user)):
    return {"schema": db.load_schema(ident["tenant"]["db_url"], refresh=True)}


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest, ident: dict = Depends(auth.current_user)):
    q = (req.question or "").strip()
    if not q:
        raise HTTPException(400, "Question is empty.")
    tenant = ident["tenant"]
    db_url = tenant["db_url"]
    dialect = db.dialect_of(db_url)
    try:
        schema = db.load_schema(db_url)
        raw_sql = llm.question_to_sql(q, schema, dialect=dialect)
        sql = sanitize(raw_sql)
        log.info("[tenant %s] Q: %s | SQL: %s", tenant["id"], q, sql)
        columns, rows = db.run_select(db_url, sql)
        # Cost optimization: a single scalar result needs no second LLM call.
        if len(rows) == 1 and len(columns) == 1:
            col = columns[0]
            val = rows[0][col]
            money = any(k in col.lower() for k in
                        ("revenue","amount","total","paid","balance","outstanding","due","expense","sales","payment"))
            label = col.replace("_", " ").strip().capitalize()
            try:
                shown = f"{settings.CURRENCY}{float(val):,.2f}" if (money and val is not None) else str(val)
            except (TypeError, ValueError):
                shown = str(val)
            narration = {"answer": f"{label}: {shown}", "chart": {"type": "none"}}
        else:
            narration = llm.narrate(q, rows)
        return AskResponse(
            answer=narration.get("answer", ""),
            sql=sql,
            columns=columns,
            rows=rows,
            chart=ChartSpec(**(narration.get("chart") or {"type": "none"})),
        )
    except UnsafeSQLError as e:
        raise HTTPException(400, f"Rejected unsafe query: {e}")
    except HTTPException:
        raise
    except Exception as e:  # pragma: no cover
        log.exception("ask failed")
        name = type(e).__name__
        text = str(e)
        if "workspace-id is required" in text or "anthropic-workspace-id" in text:
            msg = "Your Anthropic key is workspace-linked. Add ANTHROPIC_WORKSPACE_ID=wrkspc_... to backend/.env, then restart."
        elif name in ("AuthenticationError", "PermissionDeniedError") or "401" in text or "Unauthorized" in text:
            msg = "AI key not accepted (401 Unauthorized). Create a fresh key at console.anthropic.com and paste the FULL key into backend/.env, then restart."
        elif name == "NotFoundError" or ("model" in text.lower() and "not" in text.lower()):
            msg = f"The AI model '{settings.MODEL}' was not found. Update MODEL in backend/.env to a current Claude model, then restart."
        elif name == "RateLimitError" or "credit balance" in text.lower() or "429" in text:
            msg = "AI request was rate-limited or the account is out of credit. Add credit at console.anthropic.com and retry."
        elif name in ("APIConnectionError", "APITimeoutError") or "connect" in text.lower():
            msg = "Could not reach the AI service. Check this PC's internet connection and retry."
        else:
            msg = "Could not answer that. Try rephrasing."
        raise HTTPException(500, msg) from e
