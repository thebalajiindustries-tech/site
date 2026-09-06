# Ganak — Development Status & Roadmap

_Last updated: 2026-09-06. This is a living document — update the "Current
status" and "Next up" sections as work progresses rather than starting a new
file each time._

## 1. What Ganak is

Ganak is a multi-tenant "ask your business data" SaaS product for The Balaji
Industries / VidmahiTech. A company logs in, asks a plain-English question
("what's my outstanding balance?"), and Ganak turns it into a read-only SQL
query against that company's own data, runs it, and narrates the answer back
in plain English with a chart where useful. It also reads uploaded PDFs
(invoices, bills, payment advices) and files their extracted fields into the
warehouse, and can answer "right now" questions straight from Zoho Books
without needing the data pre-loaded.

Two companies are seeded out of the box: **The Balaji Industries** (real
data) and **Demo Traders** (sample data, safe to show anyone). Anyone can
also self-register a new company from the login screen.

## 2. Architecture

```
Browser (Next.js frontend)
   |  Bearer token
   v
FastAPI backend
   |
   +-- auth.py       password hashing (PBKDF2), signed tokens, brute-force lockout
   +-- tenancy.py     control plane: which companies + users exist, wallet balance
   +-- db.py          per-tenant READ-ONLY connections (Postgres schema or SQLite file)
   +-- guardrails.py  blocks anything but a single SELECT/WITH before it ever runs
   +-- llm.py         question -> SQL (Claude), rows -> plain-English answer
   +-- zoho_live.py   "Live" mode: answers straight from the Zoho Books API, no warehouse
   +-- docai.py       PDF -> structured fields (Claude's native document support)
   +-- docstore.py    the ONLY writable path — fixed, parameterized insert into `documents`
   +-- billing.py     meters Claude token usage into an INR cost per request
   +-- seed.py        bootstraps demo companies + provisions new signups
```

**Multi-tenancy / isolation.** Every company is a separate Postgres *schema*
inside one shared Supabase database (or, in local dev, its own SQLite file).
Isolation is enforced at the connection layer — a request is authenticated,
the caller's tenant is resolved, and every query for that request runs
against *only* that tenant's schema. The AI-generated SQL is never trusted to
respect boundaries by itself.

**The `/ask` pipeline**, step by step:
1. Reject empty / absurdly long questions, and block the request with HTTP
   402 if the company's wallet balance is empty.
2. Load that tenant's schema (table + column names only — cached).
3. Claude turns the question into one SQL query (dialect-aware: Postgres vs
   SQLite syntax differ for dates/casts).
4. `guardrails.sanitize()` rejects anything that isn't a single
   SELECT/WITH statement, and enforces a row limit.
5. Run it on a connection that is set `READ ONLY` at the database session
   level (Postgres) or `PRAGMA query_only` (SQLite) — belt and suspenders on
   top of the SQL-text check.
6. A single-value result (e.g. "what's my total revenue") is templated
   directly, skipping a second Claude call, to save cost; anything else goes
   through Claude once more to narrate the rows and pick a chart type.
7. Meter the tokens spent, convert to INR, debit the company's wallet, log
   the transaction to the ledger.

**Billing.** Every AI call (NL→SQL, narration, document extraction) meters
its Anthropic token usage. `billing.py` converts that to a cost in INR
(configurable USD→INR rate + markup) and `/ask`, `/documents/extract` debit
the company's prepaid wallet balance, recording each transaction to
`usage_ledger`. Recharge is currently simulated (`POST /billing/recharge`) —
see "Not built yet" below for real payments.

**Safety model** (see `backend/tests/test_hardening.py` for the executable
spec): SQL injection / write attempts are blocked with a friendly message
that never leaks the rejection reason to a would-be attacker; off-topic
questions get the same friendly redirect; failed logins lock out after 5
attempts in 15 minutes; transient Anthropic errors (rate limit, timeout,
overload) are retried automatically before surfacing an error to the user.

## 3. Current status

All of the below is built and covered by an automated test in
`backend/tests/` (run with `python tests/test_*.py` from `backend/`, or all
of them in a row — no test framework needed, they're self-contained scripts
that spin up the real FastAPI app against temporary SQLite databases):

- Multi-tenant auth + isolation (`test_isolation.py`) — register, login,
  tampered-token rejection, cross-tenant data leakage checks
- Hardening (`test_hardening.py`) — injection/write attempts, off-topic
  questions, question-length limit, login lockout
- Document AI (`test_documents.py`) — PDF upload → extract → review → load
  → immediately queryable
- Pay-as-you-go billing (`test_billing.py`) — metering, wallet debit,
  recharge, empty-balance lockout
- Live Zoho query mode (`test_live.py`) — answers straight from the Zoho API

**Also done, not covered by the local test suite (needs your own hosted
Supabase/Zoho credentials to test):**
- Every tenant's data (control plane + Balaji + Demo Traders + future
  signups) now lives on Supabase Postgres, one schema per tenant, instead of
  a mix of local Postgres + SQLite files. This was required because a
  cloud-hosted backend can't reach a database on your Windows PC.
- Gmail finance-email snapshot loaded into Balaji's warehouse
  (`backend/connectors/load_gmail_snapshot.py`, ~43 records) as an `emails`
  table, queryable alongside invoices/payments/expenses.
- Cost optimizations: Haiku for everyday NL→SQL/narration, Sonnet only for
  PDF extraction; prompt caching on the schema+rules prefix; single-value
  answers skip the second Claude call; dashboard KPIs cached client-side for
  10 minutes.

**Deployment status (update this as you go):**
- [x] Supabase project created and connected (`SUPABASE_DB_URL`,
      `CONTROL_DB_URL` in `backend/.env`)
- [x] Code pushed to GitHub: `thebalajiindustries-tech/site`, branch `ganak`
- [ ] `migrate_balaji_to_supabase.bat` run to copy Balaji's real Zoho data
      from the local Postgres warehouse into the Supabase `balaji` schema
      **— not done yet, do this before relying on production for real
      numbers**
- [ ] Render Blueprint deployed (`ganak-backend` + `ganak-frontend`)
- [ ] `api.vidmahitech.com` / `app.vidmahitech.com` DNS attached in
      Cloudflare and verified in Render
- [ ] Smoke test against the real production URLs (login, ask, billing)

See `DEPLOY.md` for the full step-by-step for the remaining items.

## 4. Repo map

```
ganak/
  backend/
    app/               FastAPI application (see architecture above)
    tests/             self-contained test scripts, no framework needed
    Dockerfile          used by Render to build the backend
    requirements.txt
    .env                 secrets + config -- never committed (see .gitignore)
  frontend/
    app/                Next.js pages: login, dashboard, ask, billing, documents, connections
    lib/api.ts           typed fetch wrapper for every backend endpoint
    Dockerfile           used by Render to build the frontend
  render.yaml            Render Blueprint -- both services in one file
  DEPLOY.md              step-by-step production deployment guide
  DEVELOPMENT.md         this file
  CLAUDE.md / RUN_LOCAL.md   local dev context and instructions
  start.bat              one-click local dev launcher (Windows)
  push_to_github.bat / verify_push.bat   deploy-branch push + verification
  migrate_balaji_to_supabase.bat/.py     one-off: copy local Postgres -> Supabase
  test_supabase.bat/.py, debug_startup.bat/.py   diagnostics used while migrating
```

## 5. Local development

See `RUN_LOCAL.md` for full detail. Short version: double-click `start.bat`.
Demo logins: `balaji@ganak.local` / `balaji123` and `demo@ganak.local` /
`demo123`.

## 6. Not built yet (known gaps)

- **Real payments.** `/billing/recharge` is a simulated top-up. Production
  needs a Razorpay (or similar) integration: the frontend collects payment,
  Razorpay's webhook calls the backend to actually credit the wallet.
- **Self-serve data connections.** The Connections page
  (`frontend/app/connections/page.tsx`) is currently a static status display
  for the two seeded demo companies — a brand-new signup gets an empty
  warehouse with no way to connect their own Zoho/Gmail from the UI yet.
  Today the only way to get data into a new tenant's warehouse is the
  Documents (PDF upload) feature. A real "Connect Zoho Books" OAuth flow per
  tenant is the natural next step to make self-serve signups actually
  useful.
- **Zoho incremental sync freshness.** Before the Supabase migration, there
  was an open question about whether `zoho_postgres_sync.py`'s incremental
  sync was actually pulling recent (Apr-Sep 2026) records into Balaji's
  warehouse, or was stuck on an old full sync. This was deprioritized in
  favor of building Live mode (which bypasses the warehouse entirely) as a
  working alternative. Worth revisiting: run `refresh_data.bat` in
  `PyProject/`, check `refresh_output.log`, and confirm recent months show
  up in warehouse-mode answers.
- **Cold starts.** Render's free tier spins both services down after 15
  minutes idle (~1 minute to wake back up). Fine for early use; a paid plan
  removes this once there's real customer traffic that can't tolerate the
  delay.

## 7. Suggested next steps, roughly in order

1. Finish the in-progress production deploy (Render Blueprint → Cloudflare
   DNS → smoke test) per `DEPLOY.md`.
2. Run `migrate_balaji_to_supabase.bat` and confirm Balaji's real numbers
   show up correctly in production.
3. Delete `github_token.txt` from the project folder once the GitHub push
   is confirmed working (it's git-ignored, but no reason to leave a live
   token sitting in a plaintext file longer than needed).
4. Investigate the Zoho incremental sync freshness question above.
5. Decide on and build real payments (Razorpay) once ready to onboard
   paying customers beyond the two demo companies.
6. Build the self-serve "connect your own Zoho/Gmail" flow — this is what
   makes a new signup actually useful without manual setup.
7. Revisit the AI-automation wishlist from earlier in this project (PDF →
   data is done; other ideas raised were open-ended "many more features
   which is possible" — worth a follow-up conversation on what's highest
   value next: bank-statement reconciliation, WhatsApp query access,
   scheduled email digests, etc.)
