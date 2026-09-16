# OpenAI Usage & Cost Dashboard

Organization-wide OpenAI usage and spend — by project, API key and model — with
live model pricing, a date-range filter and a formatted Excel export.

React + Vite + TypeScript frontend, FastAPI backend. The API key never reaches the
browser: the backend is the only thing that talks to OpenAI.

---

## ⚠️ You need an **Admin** key, not a project key

The organization endpoints this dashboard reads require an **Admin key**
(`sk-admin-…`). The `sk-proj-…` key in the repo root `.env` is a *project* key and
returns 403 — verified:

```
403 GET /v1/organization/projects          Missing scopes: api.management.read
403 GET /v1/organization/usage/completions Missing scopes: api.usage.read
403 GET /v1/organization/costs             Missing scopes: api.usage.read
200 GET /v1/models                         (project keys work here)
```

Create one as an **Organization Owner** at
<https://platform.openai.com/settings/organization/admin-keys>, then:

```bash
cp usage_dashboard/backend/.env.example usage_dashboard/backend/.env
# edit .env and set OPENAI_ADMIN_KEY=sk-admin-...
```

Without it the dashboard runs in **demo mode** with synthetic data, clearly
flagged with a banner. Everything is explorable; only the numbers are fake.

---

## Run it

Two terminals.

**Backend** (port 8899 — 8787 is already in use on this machine):

```bash
cd usage_dashboard/backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --port 8899 --reload
```

**Frontend** (port 5173 by default; Vite proxies `/api` → `127.0.0.1:8899`):

```bash
cd usage_dashboard/frontend
npm install
npm run dev
```

Open the URL Vite prints. `npm run build` produces a static `dist/` you can serve
from anywhere.

---

## What it shows

**KPI tiles** — API calls, total tokens, input (with cache-hit rate), output
(tokens/call), billed cost, estimated cost and the gap between the two.

**Charts**
- *Spend over time* — billed dollars vs. token-mix estimate. A persistent gap means
  line items the token math doesn't capture (file search, batch, fine-tuning).
- *Token volume* — stacked daily input / cached-input / output.
- *API calls* — request trend.
- *Estimated cost by model* — directly labelled horizontal bars.

**Tables** — Models (unit economics: $/1M in/out, avg $/call, cache hit rate),
Accounts, Projects (billed + estimated side by side), API keys, billed cost by
line item, and the full live rate card with a filter box.

**Usage report** — the client-facing credit summary: top-ups, usage by client and
period, balance, disputed charges, documents processed. See below.

**Filters** — 7D / 30D / 90D / MTD presets, custom from–to, granularity
(daily / hourly / per-minute), an account selector and a project selector.

**Excel export** — the `Download Excel` button hits `/api/export.xlsx` with the
current filters and returns a 10-sheet workbook: Usage Summary · Summary ·
Daily Usage · By Model · By Account · By Project · By API Key · Billed Costs ·
Cost by Line Item · Model Rate Card.
Every sheet has frozen headers, autofilters, tuned column widths and real Excel
number formats (currency, thousands separators, percentages) — no cleanup needed.

---

## Auto-refresh

The dashboard polls for new usage on its own — the picker in the toolbar offers
**30s / 1m / 5m / 15m / Off** (default 1m, remembered per browser).

- Polling **pauses while the browser tab is hidden** and resumes on focus, so a
  dashboard left open overnight makes no requests.
- Charts **stay on screen** during a refetch (previous data is kept) — no flash
  back to a loading state. The sidebar pill switches to "Syncing…" and the footer
  shows `Updated 12s ago`.
- **Refresh** forces a live re-read, bypassing the server cache.

### Server-side cache

The backend caches each `(range, granularity, projects)` payload for
`CACHE_TTL_SECONDS` (default **30**). Without it, N open dashboards × M polls
would become N×M upstream calls against the Admin API's rate limits.

Measured on the live org:

```
poll 1 (cold)          3.24s   cache_age=0.0s
poll 2 (cached)        0.005s  cache_age=3.3s
poll 3 (cached)        0.004s  cache_age=3.3s
refresh=true (bypass)  2.99s   cache_age=0.0s
```

Tune with `CACHE_TTL_SECONDS` in `backend/.env`. Note OpenAI's usage aggregation
has its own upstream lag of minutes, so polling faster than ~30s gains nothing.

---

## Multiple accounts

The dashboard reads any number of OpenAI organizations at once and merges them
into one view. Accounts are declared in `backend/accounts.json`; the Admin keys
themselves stay in `backend/.env`, named by `key_env`:

```jsonc
{
  "accounts": [
    { "id": "acct-hnb",    "label": "Acceltree - HNB",
      "key_env": "OPENAI_ADMIN_KEY",   "attribute_by": "project" },
    { "id": "acct-legacy", "label": "Acceltree Software Pvt. Ltd",
      "key_env": "OPENAI_ADMIN_KEY_2", "attribute_by": "api_key" }
  ]
}
```

Every usage, cost and project row is tagged with the account it came from, so the
**Accounts** tab, the account filter and the `By Account` sheet all work without
each org having to be queried separately. An org whose key is missing or is a
project key is shown as unusable rather than silently dropped.

---

## Usage report — credits, clients, balance

The **Usage report** tab (and the `Usage Summary` sheet, the first tab of the
workbook) is the client-facing credit summary: top-ups, usage split by client and
period, balance remaining, disputed charges held out, and documents processed.

Dollar figures are billed amounts from the Costs API. Everything OpenAI cannot
tell us lives in `backend/report_config.json`:

| Key | What it does |
|---|---|
| `client_mapping` | account → project id (or API-key name) → client |
| `top_ups` | credit top-ups; the report splits periods at each of these dates |
| `exclusions` | charges held out of client usage, e.g. a disputed incident. `baseline_retained` keeps that day's normal spend with the client |
| `documents` | documents processed per month per environment — placeholder until the DB is wired in |

**Two attribution styles.** `attribute_by: "project"` is exact: the Costs API
groups by `project_id`, so each client's dollars are measured. `attribute_by:
"api_key"` is for an org that keeps every client in a single project — the Costs
API cannot group by API key, so that project's daily cost is apportioned across
keys by their token spend. Apportioned clients are marked `*` in both the UI and
the workbook, and the report says so in its notes.

---

## Billing tab — history & balance

### What OpenAI does *not* expose

Credit balance and invoices are **not available to any API key**, Admin included.
Verified against the live org:

```
403 GET /v1/dashboard/billing/credit_grants   "must be made with a session key ... only from the browser"
403 GET /v1/dashboard/billing/subscription    same
403 GET /v1/dashboard/billing/invoices        same
404 GET /v1/organization/billing/*            no such endpoint
404 GET /v1/organization/invoices             no such endpoint
200 GET /v1/organization/costs                works
```

Those endpoints are session-authenticated for the browser only. No key gets past that.

### Billing history — real

Monthly totals come from `GET /v1/organization/costs`, the same spend OpenAI bills:
per calendar month, active days, average per day, month-over-month change, and a
per-project breakdown across months. Selectable 3 / 6 / 12 / 24 months. Leading
months with no spend are trimmed.

### Remaining balance — declared, then drawn down

Since the API won't give a balance, you record one: enter the figure from your
OpenAI billing page and the date you read it. The dashboard then subtracts **real
billed spend** since that date and derives:

- **Remaining** = recorded amount − billed spend since `as_of`
- **Burn rate** — trailing 30 days *and* lifetime average
- **Runway** — days left, and the projected depletion date
- **Status** — Healthy / Watch / Low (< 45d / < 14d), always with a label, never colour alone

Runway is based on **whichever burn rate is higher**. Lifetime average flatters the
estimate when spend is accelerating — on this org the difference was 31 days
(lifetime $2.54/day) versus 15 days (trailing 30d $5.23/day). The banner states
which basis was used.

If your recorded `as_of` predates the fetched history, `covers_full_period` goes
false and the UI warns that spend-since may be understated.

Stored in `backend/balance.json` (gitignored) so it is shared across browsers.
`PUT /api/billing/balance` `{amount, as_of, note}` · `DELETE` to clear.

---

## Where the numbers come from

| Number | Source |
|---|---|
| Tokens, requests, cache hits | `GET /v1/organization/usage/*`, grouped by project / api_key / model |
| **Billed** cost | `GET /v1/organization/costs` — authoritative, what OpenAI charges |
| **Estimated** cost | token mix × live rates (computed here) |
| Live rates | [LiteLLM `model_prices_and_context_window.json`](https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json) |
| Project & key names | `GET /v1/organization/projects`, `…/api_keys` |

Both cost figures are shown deliberately. Billed is the truth; estimated breaks the
bill down per model and per call in a way the Costs API does not.

Pricing is cached to `backend/pricing_cache.json` with a 6-hour TTL, falls back to
a stale cache when offline, and finally to a small built-in table — so the
dashboard never renders $0 for a known model. `GET /api/pricing?refresh=true`
forces a re-fetch. Model IDs are resolved leniently: `gpt-4o-2024-08-06` and
`ft:gpt-4o:…` both fall back to `gpt-4o`'s rates; anything unresolvable is marked
`unpriced` rather than silently counted as free.

---

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | key status (never echoes the key), live/demo, pricing source |
| `GET /api/accounts` | configured organizations and their key health |
| `GET /api/dashboard` | everything the UI renders |
| `GET /api/report` | the credit/usage summary (top-ups, clients, balance) |
| `GET /api/projects` | project list, across accounts |
| `GET /api/pricing` | live rate card (`?refresh=true` to force) |
| `GET /api/export.xlsx` | the workbook |

`/api/health` is always reachable (platform health checks); every other path is
behind basic auth when `DASHBOARD_PASSWORD` is set.

Shared params: `start`, `end` (`YYYY-MM-DD`), `bucket_width` (`1d`\|`1h`\|`1m`),
repeatable `project_ids` and `account_ids`. Range is capped at 366 days.

---

## Notes

- **Charts** follow a validated palette — light and dark both pass the CVD,
  lightness and chroma checks. Light mode warns on contrast for three series
  slots, so every chart ships a legend, direct labels and a table toggle rather
  than relying on colour alone. Theme follows the OS and can be overridden.
- **Pagination** is handled on every endpoint (`next_page` / `after`), so long
  ranges return complete data rather than the first page.
- **Rate limits and 5xx** are retried with exponential backoff.
- **Usage kinds** — completions, embeddings, images, audio speech and
  transcriptions are fetched concurrently; a kind your org has never used
  returns nothing rather than failing the request.
- **Secrets** — API key *values* are never returned by OpenAI's API and never
  displayed. The Admin key stays server-side; add auth in front of this service
  before exposing it beyond localhost.

---

## Deploy to Render (Free Tier)

Canonical repository: **`Acceltree-Software/openai-account-management`** (private).

1. [render.com](https://render.com) → **New Web Service** → connect the repo.
   Render needs access to the Acceltree-Software org: if the repo does not
   appear, use *Configure account* on the GitHub connection and grant it.
2. Render detects the `Dockerfile`. Runtime **Docker**, branch `main`, plan Free
   — everything else is in `render.yaml`.
3. Set the environment variables (Environment → Add):

   | Key | Notes |
   |---|---|
   | `OPENAI_ADMIN_KEY` | first organization's `sk-admin-…` |
   | `OPENAI_ADMIN_KEY_2` | second organization's key |
   | `DASHBOARD_PASSWORD` | **required.** Without it the service returns 503 rather than serving org spend unauthenticated |
   | `DASHBOARD_USER` | optional, defaults to `admin` |

4. Deploy. First build takes ~2–3 min; the free plan sleeps after 15 min idle.

Health checks hit `/api/health`, which stays reachable without credentials by
design. Every other route requires the password.

### Repointing an existing service

A service already connected to another repository keeps building from it —
changing `render.yaml` does not move it. Go to **Settings → Build & Deploy →
Repository → Update**, pick this repo, then **Manual Deploy → Deploy latest
commit**. Environment variables are attached to the service, not the repo, so
they survive the switch.
