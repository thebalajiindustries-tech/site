# Connectors — feeding the Ganak warehouse

Ganak answers questions from one Postgres warehouse. These connectors keep it
filled. Each is read-only against the source and only appends/updates in Postgres.

## Zoho Books  ✅ (already running)

Your existing `zoho_postgres_sync.py` + `zoho_scheduler.py` sync invoices,
expenses, bills, payments, customers, etc. into Postgres. Nothing to change —
Ganak reads those tables directly. Keep the scheduler running.

## Gmail  ✅ (new — `gmail_sync.py`)

Pulls Balaji's finance emails into an `emails` table so the AI can answer across
Zoho **and** email. Auto-classifies each message:

| category              | example source                          |
|-----------------------|-----------------------------------------|
| `payment_received`    | Zoho Books "Payment Received" notices   |
| `bank_payment_advice` | Deutsche Bank payment advices           |
| `vendor_bill`         | supplier bills / "make payment" emails  |
| `balance_confirmation`| year-end balance confirmation requests  |
| `quotation`           | incoming/outgoing quotations            |
| `purchase_order`      | PO acknowledgements / statements        |

It also parses the ₹ amount when one appears, and marks each email
incoming/outgoing.

### One-time setup
1. Google Cloud Console → enable **Gmail API** → create an **OAuth client (Desktop app)**
   → download `credentials.json` into this `connectors/` folder.
2. `pip install -r requirements-gmail.txt`
3. `python gmail_sync.py full` — a browser opens once to authorize
   `thebalajiindustries7333@gmail.com` (read-only), then it stores `token.json`
   and syncs the last 12 months.

### Keep it fresh
```
python gmail_sync.py incremental     # only new mail since last sync
```
Add it to the same Windows Task Scheduler job as your Zoho sync (e.g. hourly).

### Ask across both sources
Once synced, the AI sees the `emails` table automatically. Try:
- "Show me the payment-received emails over ₹1 lakh this year"
- "Which vendors sent balance confirmations?"
- "How many bank payment advices did I get last month?"

Tuning the classifier or the search query? Edit `classify.py` and the
`GMAIL_QUERY` env var.
