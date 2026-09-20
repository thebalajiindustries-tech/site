# Ganak — Staging Environment & Development Cycle

_Added 2026-09-19. This is the process to follow from now on: never edit
code directly against the live production services again — everything goes
through staging first._

## 1. The two environments

| | Production | Staging |
|---|---|---|
| Frontend | `ganak-frontend` → https://app.vidmahitech.com | `ganak-frontend-zubq` → https://ganak-frontend-zubq.onrender.com |
| Backend | `ganak-backend` → https://api.vidmahitech.com | `ganak-backend-zubq` → https://ganak-backend-zubq.onrender.com |
| Git branch | `ganak` | `staging` |
| Database | Supabase, schemas `control`, `balaji`, `demo_traders`, ... | **same Supabase project**, schemas `staging_control`, `staging_balaji`, `staging_demo_traders`, ... |
| Shows a banner? | No | Yes — a yellow "STAGING — TEST ENVIRONMENT, NOT YOUR REAL DATA" bar on every page |

Staging is not a toy — it runs the same code, against the same shared
Supabase database, with real Anthropic/Zoho calls. The only difference is
the `GANAK_SCHEMA_PREFIX=staging_` env var on the backend, which makes every
schema name it touches (control plane + every tenant warehouse) start with
`staging_`. That prefix makes it physically impossible for staging to read
or write a production row — it is a different set of tables entirely, in
the same database.

Both staging services are on Render's **free tier**, so:
- They spin down after ~15 minutes of no traffic — the first request after
  that takes 50+ seconds to wake up. That's expected, not a bug.
- They share Render's free monthly build-minute pool with the rest of the
  account, so avoid pushing dozens of tiny commits back to back.

## 2. The development cycle

```
   your changes
        |
        v
  git checkout staging        (or a feature branch cut FROM staging)
  ...edit code...
  git commit
  git push site staging       -> Render auto-deploys BOTH -zubq services
        |
        v
  test at https://ganak-frontend-zubq.onrender.com
  (staging banner + separate staging_* schemas — safe to break)
        |
        v
  happy with it?
        |
        v
  git checkout ganak
  git merge staging
  git push site ganak         -> Render auto-deploys the REAL app.vidmahitech.com
```

Step by step:

1. **Branch off `staging`** for any new work (or commit straight to
   `staging` for small fixes):
   ```
   git checkout staging
   git pull site staging
   git checkout -b feature/my-change      # optional, for bigger changes
   ```
2. **Push to `staging`** (merge your feature branch back into `staging`
   first if you used one). Render's auto-deploy is already wired to the
   `staging` branch for both `-zubq` services — a push is all it takes:
   ```
   git push site staging
   ```
3. **Watch the deploy** in the Render dashboard (Deploys tab on either
   `-zubq` service) — usually 30–90 seconds for the backend, 2–4 minutes for
   the frontend (Next.js build).
4. **Test on staging**: https://ganak-frontend-zubq.onrender.com. Log in
   with the demo account (`demo@ganak.local` / `demo123`) or register a
   fresh test company — either way it's isolated in `staging_*` schemas and
   can't touch anything real. Confirm the yellow staging banner is showing;
   if it's not, something is wrong with the deploy (see "How to tell staging
   and production apart" below).
5. **Promote to production** only once you're satisfied:
   ```
   git checkout ganak
   git merge staging
   git push site ganak
   ```
   This deploys to the real `ganak-backend` / `ganak-frontend` services and
   the real `app.vidmahitech.com` / `api.vidmahitech.com` domains.
6. **Never** edit `render.yaml` for staging-only settings — it's shared with
   production's Blueprint. All staging-specific configuration (branch, env
   vars, build args) lives directly on the `-zubq` services' own dashboard
   settings, set once and left alone.

## 3. How to tell staging and production apart

- Staging always shows the yellow **"STAGING — TEST ENVIRONMENT, NOT YOUR
  REAL DATA"** bar at the top of every page. Production never shows it.
- Staging's URL is `ganak-frontend-zubq.onrender.com` / API responses come
  from `ganak-backend-zubq.onrender.com`. Production is
  `app.vidmahitech.com` / `api.vidmahitech.com`.
- If you're ever unsure which one you're looking at, check for the banner
  first — it's the fastest tell.

## 4. One-time setup already done (for reference — don't repeat this)

- `GANAK_SCHEMA_PREFIX=staging_` and `GANAK_ENVIRONMENT=staging` set on
  `ganak-backend-zubq`'s environment variables.
- `PUBLIC_API_BASE_URL` / `PUBLIC_APP_BASE_URL` on `ganak-backend-zubq`
  pointed at the `-zubq` URLs instead of the real domains (needed for OAuth
  redirect URIs and links in emails to resolve correctly on staging).
- `CORS_ORIGINS` on `ganak-backend-zubq` set to
  `https://ganak-frontend-zubq.onrender.com`.
- `NEXT_PUBLIC_API_URL=https://ganak-backend-zubq.onrender.com` and
  `NEXT_PUBLIC_APP_ENV=staging` set on `ganak-frontend-zubq` (these are
  Docker build args baked in at build time, same mechanism as production's
  `NEXT_PUBLIC_API_URL`).
- Both `-zubq` services' Branch setting changed from `ganak` to `staging`.

## 5. ⚠️ Action needed: missing secrets on the staging backend

`ganak-backend-zubq` is currently **missing four secret environment
variables** that exist on the production `ganak-backend` service:

- `ANTHROPIC_API_KEY`
- `ANTHROPIC_WORKSPACE_ID`
- `SUPABASE_DB_URL`
- `CONTROL_DB_URL`

Without `CONTROL_DB_URL` set, the backend falls back to local, ephemeral
SQLite instead of the shared Supabase project — which means:
- Staging currently **works** for testing UI/flow (login, asking questions
  against the seeded demo data, etc.) because the app boots fine without
  these.
- But it is **not yet using the `staging_*` Supabase schemas** as designed —
  its data lives in a throwaway SQLite file inside the container and is
  **wiped on every redeploy or restart**.
- The `ANTHROPIC_API_KEY` gap means `/ask` (asking a question) will fail
  once wallet/billing logic needs a real Claude call, if a key isn't picked
  up from some other fallback.

**To fix:** open `ganak-backend-zubq` → Environment in the Render dashboard
and add those four keys with the same values as the production
`ganak-backend` service. I did not view or copy these values myself since
they're secrets — you'll need to copy them from `ganak-backend`'s own
Environment tab. Once added and saved, the service will redeploy and start
using the real shared-Supabase-with-prefix design described in section 1.

## 6. Still pending / deferred

- **Zoho multi-account OAuth picker**: when a user connects Zoho and their
  account has multiple Zoho organizations, the app currently just takes the
  first one (`backend/app/connectors_routes.py`, `org = orgs[0]  # first-cut`).
  Adding an account-selection step is scoped but not yet built — develop it
  on `staging` first per the cycle above.
- **Password reset**: no admin-set-password or self-serve email-reset flow
  exists yet. Passwords are one-way hashed (PBKDF2-SHA256) and cannot be
  recovered, only reset.
