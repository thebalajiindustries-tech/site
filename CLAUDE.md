# Ganak

Multi-tenant ask-your-data assistant (VidmahiTech). A business user asks a
natural-language question about their finances; Ganak turns it into **read-only**
SQL, runs it against **that company's own database**, and answers in plain English
with an optional chart.

## Multi-tenancy (foundation)
- **Isolation model:** one database per company. A request is authenticated, the
  caller's company is resolved from a small **control plane**, and the pipeline
  runs only against that company's `db_url`. The AI can never reach another
  company's data — isolation is enforced at the connection, not in generated SQL.
- **Control plane:** `backend/ganak_control.db` (SQLite) — companies + users.
- **Tenant data:** per company. Postgres (`postgresql://…`) or SQLite (`sqlite:///…`).
- **Auth:** email + password (PBKDF2 hashing) with HMAC-signed tokens — Python
  stdlib only (`app/auth.py`). Swap for passlib/JWT in production.

### Demo logins (seeded on first run)
- **The Balaji Industries** — real Zoho→Postgres warehouse — `balaji@ganak.local` / `balaji123`
- **Demo Traders** — self-contained SQLite sample data — `demo@ganak.local` / `demo123`
Logging in as one company never shows the other's data. Change these before production.

## Structure
- `backend/app/main.py`      — API: /auth/register, /auth/login, /me, /ask, /schema, /health, /ping
- `backend/app/auth.py`      — password hashing + signed tokens + current_user dependency
- `backend/app/tenancy.py`   — control-plane (companies + users) in SQLite
- `backend/app/db.py`        — read-only, tenant-aware data access (Postgres + SQLite)
- `backend/app/llm.py`       — question→SQL (dialect-aware) + narrate
- `backend/app/guardrails.py`— single-SELECT sanitizer (no writes/DDL/multi-statement)
- `backend/app/seed.py`      — bootstrap demo companies + provision new tenant DBs
- `backend/tests/test_isolation.py` — auth + cross-tenant isolation tests
- `frontend/`                — Next.js 14: login, dashboard, Ask chat; token in localStorage

## Run locally (Windows)
Right-click `start.bat` → Run as administrator. App: http://localhost:3000 →
sign in with a demo login above. Backend: http://localhost:8000/ping .

## Tests
    cd backend && python tests/test_isolation.py    # proves cross-company isolation

## Required env (`backend/.env`, NOT committed)
    DATABASE_URL=postgresql://postgres:<pw>@localhost:5432/the_balaji   # Balaji tenant warehouse
    LLM_PROVIDER=anthropic
    ANTHROPIC_API_KEY=sk-ant-...
    ANTHROPIC_WORKSPACE_ID=wrkspc_...    # identity-linked keys
    MODEL=claude-sonnet-5
    GANAK_AUTH_SECRET=<random>           # signs login tokens

## Safety model
The AI can only ever **read**. Every query passes `guardrails.sanitize()` (one
SELECT only) and runs on a read-only connection (Postgres READ ONLY / SQLite
query_only) with a statement timeout and row cap, against only the logged-in
company's database.

## Not yet built (next passes)
Per-company Zoho/Gmail connect flow, Stripe billing, password reset, admin roles.
