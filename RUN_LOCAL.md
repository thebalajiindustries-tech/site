# Running Ganak locally (Windows)

Ganak runs entirely on **this computer** during development. Your Zoho and Gmail
data never leaves your machine — the only thing that goes out is the AI call
itself (your question + the result rows go to Anthropic to be phrased into an
answer). Your database, passwords, and API key all stay local.

## The easy way — one double-click

1. Double-click **`start.bat`**.
2. The **first time**, it sets up the backend, then opens `backend\.env` in
   Notepad. Fill in two lines and save:
   ```
   DATABASE_URL=postgresql://postgres:YOUR_PG_PASSWORD@localhost:5432/the_balaji
   ANTHROPIC_API_KEY=sk-ant-...
   ```
   - `YOUR_PG_PASSWORD` = the PostgreSQL password you set when installing Postgres.
   - `ANTHROPIC_API_KEY` = create one at **console.anthropic.com → API Keys**
     (it stays only in this file on your PC).
3. Double-click **`start.bat`** again. It installs the frontend, launches both
   services, and opens the app.

- **App:** http://localhost:3000  → click **Ask Ganak**
- **Backend health:** http://localhost:8000/health (should say `database: up`)

To stop Ganak, just close the two black windows that opened.

## Load your real Gmail emails (optional, one time)

Double-click **`load-sample-emails.bat`** to drop 23 of Balaji's real finance
emails into the warehouse, then ask things like *"show payment-received emails
over ₹1 lakh this year"*. For the **full** live Gmail sync later, see
`backend/connectors/README.md`.

## Requirements (install once, if you don't have them)

- **Python 3.11+** — https://www.python.org/downloads/ (tick "Add to PATH")
- **Node.js 18+** — https://nodejs.org/
- **PostgreSQL** with your `the_balaji` database — the one your
  `zoho_postgres_sync.py` already fills. Keep that sync running so the data
  stays fresh.

## First questions to try

- "What's my paid revenue for the last 6 months?"
- "Who owes me the most money right now?"
- "Break down my expenses by category this quarter"
- "Show payment-received emails over ₹1 lakh this year"  *(after loading emails)*

Every answer shows the **SQL Ganak wrote** (click "view the SQL") so you can
verify it. The AI can only ever **read** — it can't change or delete anything.

## Costs while developing

Only the AI usage — a few paise per question on Anthropic. Everything else
(Postgres, the app) is free and local. When you're ready to put Ganak online for
others, see the "What's next" section in `README.md`.
