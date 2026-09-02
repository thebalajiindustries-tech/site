# Ganak

Ask-your-data assistant for **The Balaji Industries** (VidmahiTech). A business user
asks a natural-language question about their finances; Ganak turns it into **read-only**
SQL, runs it against a local PostgreSQL warehouse (synced from Zoho Books), and answers
in plain English with an optional chart.

## Structure
- `backend/` — FastAPI service (Python). NL -> SQL -> run -> narrate.
  - `app/main.py`    — `/ask`, `/health`, `/schema` endpoints
  - `app/llm.py`     — Anthropic/OpenAI calls (question_to_sql, narrate)
  - `app/db.py`      — **read-only** Postgres connection + schema introspection
  - `app/guardrails.py` — single-SELECT sanitizer (blocks writes/DDL/multi-statement)
  - `app/config.py`  — settings from `.env`
  - `connectors/`    — Gmail finance-email ingestion
- `frontend/` — Next.js 14 (App Router, TypeScript) chat + dashboard UI
- `db/`       — seed SQL + sample emails
- `start.bat` — Windows launcher (sets up venv/npm, runs both services)

## Run locally (Windows)
Right-click `start.bat` -> Run as administrator. App: http://localhost:3000 ,
backend health: http://localhost:8000/health . See `RUN_LOCAL.md`.

## Required env (`backend/.env`, NOT committed)
    DATABASE_URL=postgresql://postgres:<pw>@localhost:5432/the_balaji
    LLM_PROVIDER=anthropic
    ANTHROPIC_API_KEY=sk-ant-...
    ANTHROPIC_WORKSPACE_ID=wrkspc_...   # needed for identity-linked keys
    MODEL=claude-sonnet-5

## Safety model (important)
The AI can only ever **read**. Every query passes `guardrails.sanitize()` (one SELECT
only, no writes/DDL/comments/semicolons) and runs on a connection opened
`readonly=True` with a statement timeout and row cap. It never touches live Zoho or
bank APIs — only the synced Postgres copy.

## Data freshness
The warehouse is filled by `zoho_postgres_sync.py` (in the PyProject folder).
Re-run it (`incremental` or `full`) to pull recent months before querying.
