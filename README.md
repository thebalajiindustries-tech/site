# SSC Saathi — ssc.vidmahitech.com

Maharashtra SSC Std 10 study app (Marathi audio lessons, diagrams, quizzes, answer-sheet grading).
This `ssc` branch is separate from `main` and `ganak`.

- `web/` — the website (installable on Android as an app). `web/config.js` holds the backend address.
- AI grading/doubts use the Ganak backend: `https://api.vidmahitech.com/ssc` (code in the `ganak` branch, `backend/app/ssc_routes.py`).
- `render.yaml` — creates the static site on Render (free plan).

## One-time setup
1. Render → New → Blueprint → repo `site`, branch `ssc` (creates static site `ssc-saathi`).
2. Render → `ganak-backend` → Environment → add `SSC_ACCESS_CODES` (codes you give students, e.g. `SSC-2027`).
3. Cloudflare DNS for vidmahitech.com: `CNAME  ssc  →  ssc-saathi.onrender.com` (DNS only / grey cloud), then verify the domain in Render.
4. On Android: open https://ssc.vidmahitech.com in Chrome → menu → "Install app".
