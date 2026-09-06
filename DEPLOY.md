# Deploying Ganak to the internet

This takes Ganak from "running on Kiran's PC" to a real, permanent web address
that works from any device, anywhere. Two Render web services (backend +
frontend) plus the Supabase database you already connected, with
app.vidmahitech.com / api.vidmahitech.com as the public addresses.

Everything here is written so you do the account/DNS clicks yourself (nobody
but you should ever create accounts or approve payments on your behalf) and
Claude does the file/config work.

## What's already done

- Supabase Postgres holds the control plane and every tenant's data
  (`backend/.env` -> `SUPABASE_DB_URL`, `CONTROL_DB_URL`)
- `backend/Dockerfile` and `frontend/Dockerfile` build the two services
- `render.yaml` at the repo root describes both services as a Render
  "Blueprint" so you create them together in one flow instead of two
- `.gitignore` already excludes `.env`, `*.db`, `venv/`, `node_modules/` --
  nothing secret will be pushed to GitHub

## Step 1 — Push this repo to GitHub

Render deploys from a git repo, so the code needs a home there first.

1. Go to github.com, sign in (or create a free account), click **New
   repository**. Name it `ganak`, keep it **Private**, don't add a README
   (this folder already has one). Click **Create repository**.
2. GitHub shows you a repo URL like `https://github.com/YOUR_USERNAME/ganak.git`
   — copy it and send it to me. I'll wire up the remote and push the code
   from here; if git asks you to sign in during the push, a browser window
   will pop up on your PC — just approve it there.

## Step 2 — Deploy the Blueprint on Render

1. Go to render.com and sign up (free — GitHub sign-in is the fastest way,
   and it also grants Render access to your repos in one step).
2. Click **New** -> **Blueprint**, pick the `ganak` repo. Render reads
   `render.yaml` and shows both services (`ganak-backend`, `ganak-frontend`)
   ready to create.
3. It'll prompt you for the secret values marked `sync: false` in
   render.yaml. Open `backend\.env` in Notepad on your PC and copy each
   value across:
   - `ANTHROPIC_API_KEY`
   - `ANTHROPIC_WORKSPACE_ID`
   - `SUPABASE_DB_URL`
   - `CONTROL_DB_URL`
   - `ZOHO_REFRESH_TOKEN`, `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`, `ZOHO_ORG_ID`
     (only if you want Live-mode Zoho queries working in production; skip
     if you haven't set these up locally either)
   `GANAK_AUTH_SECRET` is generated for you automatically — don't reuse the
   local dev one.
4. Click **Apply**. Render builds both Docker images and deploys them —
   first build usually takes 3-6 minutes each. You'll get temporary URLs
   like `ganak-backend-xxxx.onrender.com` and `ganak-frontend-xxxx.onrender.com`.
5. Tell me when both show **Live** in the Render dashboard (or paste any
   error you see) and I'll do a smoke test against the real URLs before we
   attach your domain.

## Step 3 — Point your domain at Render (Cloudflare DNS)

Once both services are Live:

1. In Render, open **ganak-backend** -> Settings -> Custom Domains. It
   should already show `api.vidmahitech.com` as "pending" (from render.yaml)
   with a CNAME target like `ganak-backend-xxxx.onrender.com` — copy that
   target.
2. In Cloudflare's DNS for vidmahitech.com, add a CNAME record:
   `api` -> `ganak-backend-xxxx.onrender.com`, proxy status **DNS only**
   (grey cloud, not orange) so Render can issue its SSL certificate.
3. Repeat for the frontend: CNAME `app` -> the frontend's onrender.com
   target, also DNS only.
4. Wait a few minutes for DNS to propagate, then refresh the Custom Domains
   page in Render — both should flip from "pending" to "verified" and get a
   free SSL certificate automatically.
5. Once `api.vidmahitech.com` is verified, tell me — I'll update the
   frontend's `NEXT_PUBLIC_API_URL` build variable to use it instead of the
   temporary onrender.com URL (this triggers one more rebuild of the
   frontend only).

## Step 4 — Go live

Visit `https://app.vidmahitech.com`, log in with `balaji@ganak.local` /
`balaji123` or `demo@ganak.local` / `demo123`, ask a question, check the
billing page. Once that all works, this is genuinely live — anyone with the
URL can sign up their own company from **Create a workspace**.

## Notes / things to know going in

- **Free-tier cold start**: both services spin down after 15 minutes of no
  traffic and take about a minute to wake back up on the next request.
  Fine for early/demo use; upgrade to a paid Render plan later if that
  latency becomes a problem for real customers.
- **Nothing is written to local disk in production** — Render's free tier
  wipes the filesystem on every redeploy anyway, which is exactly why
  everything (control plane + every tenant's data) now lives in Supabase
  rather than local SQLite/Postgres files.
- **Not done yet, for later**: real payments (recharge is currently
  simulated — needs a Razorpay integration), and a self-serve "connect your
  own Zoho/Gmail" flow for new signups (today a new signup gets an empty
  warehouse and has to be loaded manually, e.g. via the Documents/PDF
  upload feature).
