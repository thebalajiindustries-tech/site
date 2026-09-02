# Ganak — production app (VidmahiTech)

Ask your business finances in plain language. A **Next.js** frontend talks to a
**FastAPI** backend that introspects your **PostgreSQL** warehouse (the one your
Zoho sync fills), turns each question into **read-only SQL** with an LLM, runs it,
and answers with a chart.

This is the single-tenant milestone: it runs on **your** data, no login/billing yet.

```
frontend/   Next.js 14 app (the product UI, built from the prototype)
backend/    FastAPI service — /ask, /schema, /health
backend/connectors/   data feeds: Zoho Books (existing) + Gmail (gmail_sync.py) → warehouse
db/         seed.sql + emails_seed.csv — sample warehouse + real Gmail starter data
docker-compose.yml
```

## Fastest way to see it working (Docker) — with sample data

```bash
cd ganak-prod
cp backend/.env.example backend/.env      # add your ANTHROPIC_API_KEY
docker compose up --build
```

- App: http://localhost:3000
- API: http://localhost:8000/health
- The bundled Postgres is seeded with realistic sample invoices/expenses, so you
  can ask real questions immediately. Swap in your real DB anytime (below).

You need **one** thing: an LLM key. Get an Anthropic key from console.anthropic.com
and put it in `backend/.env`. (To use OpenAI instead, set `LLM_PROVIDER=openai` and
`OPENAI_API_KEY`.)

## Run against YOUR real Zoho warehouse

Point the backend at the same Postgres your `zoho_postgres_sync.py` writes to.

```bash
# backend/.env
DATABASE_URL=postgresql://postgres:YOUR_PG_PASSWORD@localhost:5432/the_balaji
ANTHROPIC_API_KEY=sk-ant-...
```

Then run the two services locally (no Docker needed):

```bash
# 1) backend
cd backend
python -m venv venv && source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload                        # http://localhost:8000

# 2) frontend (new terminal)
cd frontend
npm install
cp .env.local.example .env.local                     # NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev                                           # http://localhost:3000
```

Open http://localhost:3000 → **Ask Ganak** → ask "Who owes me the most money?"
The answer, the SQL it wrote, and a chart come straight from your data.

## How it stays safe

The LLM never touches Zoho or any live API — only a read-only copy in Postgres.
Every generated query passes three guardrails (`backend/app/guardrails.py`):
read-only connection, single-`SELECT`-only sanitizer, and a hard row cap +
statement timeout. The worst a wrong query can do is return the wrong number.

## Data sources (Zoho Books + Gmail)

Both feed the same warehouse; see `backend/connectors/README.md`.

- **Zoho Books** — your existing `zoho_postgres_sync.py` already fills the tables.
- **Gmail** — `connectors/gmail_sync.py` pulls Balaji's finance emails into an
  `emails` table (payments received, bank advices, vendor bills, balance
  confirmations, quotations, POs), auto-classified with ₹ amounts parsed.
- **Try it now, no OAuth needed:** load 23 of Balaji's real emails and query them:
  ```bash
  cd backend/connectors && python load_emails_seed.py
  ```
  Then ask: "show payment-received emails over ₹1 lakh this year".

## What's next (later milestones)

- **Auth + multi-tenant:** Supabase login + row-level security so each customer
  sees only their data. (Scope a `tenant_id` per request in `backend/app/main.py`.)
- **Billing:** Stripe subscriptions + a `question_answered` usage meter.
- **Self-serve Zoho connect:** customer authorizes their own Zoho on signup.

## Deploy

- Frontend → Vercel (or the Cloudflare Pages project you already have).
- Backend → Render / Railway / Fly (Dockerfile included).
- Set `NEXT_PUBLIC_API_URL` (frontend) and `DATABASE_URL` + `ANTHROPIC_API_KEY`
  + `CORS_ORIGINS` (backend) as environment variables in each host.
