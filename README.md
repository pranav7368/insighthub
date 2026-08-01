# InsightHub

**Upload any company data → get a trustworthy analytics dashboard and an AI
analyst you can chat with.** Every number is computed deterministically from
your data and traceable to source — the AI phrases insights, it never invents
figures. Works with **any LLM provider** (Claude, OpenAI, Gemini, Ollama, …)
or fully offline with no key.

---

## Why it's different

Most "AI + BI" tools hallucinate numbers. InsightHub is built so they can't:

- **Dashboards & metrics** are pure SQL/stat computations over your rows.
- **Conversational answers** ("Ask") turn your question into a *validated
  query* (the LLM picks columns, never writes raw SQL, never produces the
  number) and answer from the executed result.
- **AI narrative & recommendations** get only the *already-computed facts* —
  never raw rows — and a **number gate** flags any figure the model introduces
  that isn't in those facts.
- If the data can't support an answer, the system **abstains** instead of
  guessing.

## Features

| Area | What you get |
|------|--------------|
| **Ingest** | CSV / Excel (→ dashboard) and PDF / Word / text (→ Q&A). Auto-detects each column as measure / dimension / date, with currency / percentage / count subtypes. Review & override anytime. |
| **Live sources** | Connect a **Google Sheet** or **public CSV URL** that stays in sync — first sync builds the dashboard, re-sync (manual or scheduled) refreshes it in place, preserving your column overrides. Fetches are **SSRF-guarded** (only public hosts; private/loopback/metadata addresses refused). |
| **Multi-table joins** | **Link two datasets** on a shared column (orders + customers on `customer_id`). Auto-suggests the join key, supports left / inner joins, and materializes the result into a **new dataset** that every analytic (dashboard, metrics, drivers, ask) works on. Rebuildable from fresh source data. |
| **Data quality** | Missing values, duplicate rows, outliers (IQR), mixed-format flags + one-click cleaning (drop duplicates, fill mean/median/mode). |
| **Dashboard** | KPI cards with MoM delta + sparklines, trend **forecast** (linear + seasonal, 95% band) with **anomaly** markers and a 3-month moving average, breakdown bars, contribution donut, **Pareto (80/20)**, **treemap**, **geographic bubble map** (when a location column is present), **correlation matrix** + **scatter**, distributions (min/median/max/σ), data-profile. |
| **Auto metrics** | MoM / QoQ / YoY growth, moving averages, standard deviation, correlations, Pareto. |
| **Certified metrics** | Define a metric once — an aggregate (`SUM(revenue)`) or a ratio (`SUM(profit)/SUM(revenue)`) — and it's computed consistently everywhere, shown on the dashboard with a **"Show SQL"** toggle so anyone can verify the exact query. Definitions are constrained (whitelisted aggregate + validated columns), never free-form SQL. |
| **Auto insights** | Deterministic "Key insights" (concentration risk, trends, anomalies, margin, leader, Pareto) — always grounded. |
| **What changed (drivers)** | Root-cause analysis: decomposes a measure's period-over-period change by dimension so you see *why* it moved ("revenue rose 12% — Delhi +₹8k drove it, Mumbai gave back ₹2k"). Deterministic, follows the active measure, switchable by dimension. |
| **AI narrative** | On-demand executive brief + prioritized **recommendations** from any LLM, with the number gate. |
| **Ask** | *Data* mode: chat with your numbers (grounded text-to-query, auto-chart) with a **"show SQL"** toggle on every answer so you can verify the exact query. *Documents* mode: cited Q&A over PDFs/Word with an abstention path. |
| **Interactivity** | Filters, **click-to-drill-down** (any bar/slice filters the whole dashboard), **day-level date range** (+ 3M/6M/12M presets), **compare** two segments or two periods side-by-side. |
| **Industry templates** | Pick **Retail, SaaS, E-commerce, Logistics or Healthcare** on the empty state and get a working dashboard in one click — realistic 12-month data **plus** the certified metrics that industry reports on **plus** a default saved view arranged to tell that story. |
| **Guided onboarding** | A first-run **product tour** spotlights the real UI (upload, live sources, templates, saved views, Ask) and adapts to what is on screen; replay it any time from the **?** in the header. |
| **Saved views** | Save the current dashboard state (filters, date range, chosen measure) **and** which sections are shown **and the order they appear in** as a named **view**; switch between views, set a **default** that auto-loads, and hide/show any section from a **Customize** menu. |
| **Drag to rearrange** | **Arrange** mode turns every dashboard section into a draggable tile — drag it, nudge it with ↑ ↓, or hide it, then save the layout into a view. Shared links reproduce the arrangement their author saved. |
| **Share** | Create a **revocable, read-only public link** to a dashboard (optionally pinned to a saved view, optionally expiring) — anyone can open it, no account needed. Backed by an unguessable 192-bit capability token. |
| **Alerts** | Watch a measure (total / latest month / month-over-month %) and **POST to a webhook** (Slack, Teams, Discord, any URL) when it crosses a threshold. Checked on a schedule; fires only on the transition into "firing" (no spam) and re-arms when it recovers. Webhook URLs are SSRF-guarded. |
| **Export** | One-click **PDF** and **PNG** of the dashboard, and **CSV** of the underlying data. |
| **Team & roles** | Invite teammates with a role — **admin** (full control + team management), **editor** (edit data & dashboards), **viewer** (read-only). Content mutations require editor+; user management is admin-only. Invites get a one-time password; members can change their own. |
| **Billing & plans** | Optional (`IH_BILLING_ENABLED`) free/pro plan gating with per-workspace quotas (datasets / members / alerts) enforced at the create points (`402` on limit). Stripe checkout + webhook-driven subscription state, or set the plan manually for self-hosted. Off by default = unlimited. |
| **Row-level security** | Scope what rows a *member* sees ("Priya sees only North and East"). Enforced by rewriting the dataset's table reference into a filtered subquery that every read path shares — dashboards, Ask, certified metrics, drivers, quality, CSV export, alerts — so the filter cannot be forgotten on one endpoint. Share links and alerts evaluate as their **author**, closing the obvious escape hatches. Fails closed if a rule's column disappears. |
| **PII masking** | Sensitive columns (email / phone / ID / person name) are detected on upload by name *and* value shape, then redacted for everyone except admins — `pr***@acme.com`, `******3210` — everywhere at once, including CSV exports and public links. Applied in the SQL projection, so the stored data is never altered and masking can be lifted again from the UI. |
| **Multi-tenant** | Signup/login (JWT), per-workspace data isolation, audit log. |

## Architecture

```
                         ┌────────────────────────── Frontend (React + Recharts) ──────────────────────────┐
  Browser ── HTTPS ──►   │  Login · Dashboard (charts, filters, drill-down, export) · Compare · Ask         │
                         └───────────────────────────────────────┬─────────────────────────────────────────┘
                                                                 │  JSON API (Bearer JWT)
                         ┌───────────────────────────────────────▼─────────────────────────────────────────┐
                         │  Backend (FastAPI)                                                                │
                         │   api/deps.py    workspace resolved from the VERIFIED token only (tenant isolation)│
                         │   ingest/        parse → detect roles → per-tenant DuckDB table  |  chunks (docs) │
                         │   analytics/     engine (SQL KPIs/trends/breakdowns) · intelligence (forecast,    │
                         │                  anomaly, growth, pareto, insights) · correlation · quality ·     │
                         │                  nlquery (text→query) · narrative (LLM brief + number gate)       │
                         │   core/sqlsafe   every identifier validated + whitelisted (SQL-injection defense) │
                         │   qa/llm.py      provider-agnostic LLM (Claude/OpenAI/Gemini/Ollama/… or offline) │
                         └───────────────────────────────────────┬─────────────────────────────────────────┘
                                                                 │
                                                          DuckDB (single file)
```

**Grounding is mechanical, not prompt-based:** identifiers pass a whitelist,
answer numbers come from executed SQL, and generated narrative is checked
against the computed facts.

## Run with Docker (full stack)

The fastest way to run the whole thing — Postgres + backend + nginx-served
frontend — with one command:

```bash
docker compose up --build      # then open http://localhost:8080
```

The frontend proxies `/api` to the backend (single origin, no CORS), data
persists in Postgres (the `pgdata` volume), connection pooling is on, and it
starts in offline AI mode. For real AI, set an LLM provider in the environment;
for production set `IH_SECRET_KEY` and `IH_ENV=production`. Orchestrators can
probe **`/api/ready`** (checks the DB) for readiness and **`/api/health`** for
liveness.

## Quickstart (local dev)

**Prerequisites:** Python 3.11+, Node 18+.

```bash
# 1. Backend
cd backend
python -m venv .venv
.venv/Scripts/activate            # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt

# 2. Frontend
cd ../frontend
npm install

# 3. Configure (optional — omit to run fully offline)
cd ..
cp .env.example .env              # then edit: set IH_SECRET_KEY and, optionally, an LLM provider

# 4. Run both (from the repo root)
./run.sh                          # Windows PowerShell: ./run.ps1
```

Open **http://localhost:5173**, click **Sign up**, create a workspace, and
upload a CSV/Excel file — the dashboard builds itself.

Without an LLM key the app runs in **offline mode**: dashboards, metrics, and
charts are fully functional; Ask and the AI narrative use deterministic
fallbacks (lower quality, zero setup).

## Choosing an LLM provider

Set two env vars (in `.env`) and the matching API key. The whole app is
provider-agnostic — nothing else changes.

| Provider | `IH_LLM_PROVIDER` | Key env var | Example `IH_MODEL` |
|----------|-------------------|-------------|--------------------|
| Claude | `anthropic` | `ANTHROPIC_API_KEY` | `claude-sonnet-4-6` |
| OpenAI | `openai` | `OPENAI_API_KEY` | `gpt-4o-mini` |
| Gemini | `gemini` | `GEMINI_API_KEY` | `gemini-1.5-pro` |
| Ollama (local, free) | `ollama` | — | `llama3.1` |
| Groq / OpenRouter / Together | `groq` / `openrouter` / `together` | `*_API_KEY` | provider model id |
| Any OpenAI-compatible | (any of above) | `IH_LLM_API_KEY` | + `IH_LLM_BASE_URL` |

## Security & deployment checklist

This build is a solid, tested foundation. Before exposing it beyond localhost:

- [x] **SQL-injection defense** — identifiers validated + whitelisted (`core/sqlsafe.py`), values always bound params.
- [x] **Tenant isolation** — workspace comes from the verified JWT, never client input; every query scoped by `workspace_id` (tested).
- [x] **Auth & roles** — bcrypt password hashing, JWT sessions, three roles (admin / editor / viewer) with content mutations gated to editor+ and user management to admins, a last-admin guard, and an audit log.
- [x] **Upload limits** — type allow-list + 50 MB cap.
- [x] **SSRF defense on all outbound URLs** — one shared guard (`core/nettrust.py`) used by data-source fetches *and* alert webhooks: validates the scheme and every resolved IP (private / loopback / link-local / cloud-metadata refused), re-validates each redirect hop, and caps the response size. Override only for trusted internal URLs via `IH_ALLOW_PRIVATE_FETCH=1`.
- [x] **Rate limiting** — per-IP sliding-window limiter (`core/ratelimit.py`) with stricter buckets for auth (brute-force) and LLM/expensive endpoints; returns `429` + `Retry-After`. Tune via `IH_RATELIMIT_*`. (Per-process — front with Redis/a gateway for multi-worker.)
- [x] **Security headers** — `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `Referrer-Policy: no-referrer` on every response.
- [x] **Configurable CORS + production guardrails** — set `IH_CORS_ORIGINS` to your exact frontend origin(s); with `IH_ENV=production` the app **refuses to start** on the insecure default secret or unset CORS. (Localhost regex remains the dev default.)
- [ ] **Set `IH_SECRET_KEY`** to a long random value (warned in dev; enforced under `IH_ENV=production`).
- [ ] **Serve over HTTPS** (terminate at your proxy/load balancer; enable HSTS there).
- [ ] **File-content scanning / sandboxed parsing** for untrusted uploads.
- [x] **Storage — Postgres backend** — set `IH_DATABASE_URL=postgresql://user:pass@host:port/db` and the app stores everything (metadata *and* per-dataset tables) in Postgres: DuckDB stays the query engine and `ATTACH`es to Postgres, so the same SQL runs but data is durable and supports concurrent connections. The single-file DuckDB remains the zero-config default. (Object storage for uploaded blobs is still a future item; a connection pool would cut per-request attach overhead.)
- [ ] **Secrets** — inject provider keys via a secrets manager, not `.env`, in production.
- [ ] **Refresh tokens / shorter JWT TTL** for real sessions (`IH_JWT_TTL_MINUTES`).

## Project structure

```
backend/
  app/
    main.py                 FastAPI app + endpoints
    core/       config · db (multi-tenant schema) · security (bcrypt/JWT) · sqlsafe
    api/deps.py             JWT → workspace principal (tenant isolation)
    ingest/                 parsers (csv/xlsx/pdf/docx/txt) + chunking + pipeline
    analytics/              detect · engine · intelligence · correlation · quality · nlquery · narrative
    qa/                     llm (multi-provider + offline) · engine · gates
    prompts/                reviewable plain-text LLM prompts
  tests/                    483 tests (pytest)
  scripts/make_sample_data.py
frontend/
  src/
    App.jsx  api.js  export.js  format.js  theme.css  App.css
    components/             dashboard, charts, ask, compare, quality, schema, auth
run.sh · run.ps1 · .env.example
```

## Testing

```bash
cd backend
IH_OFFLINE=1 .venv/Scripts/python -m pytest -q     # 483 tests, no network/keys needed
```

Covers: SQL-injection defense, tenant isolation, per-format ingestion,
auto-detection, data quality + cleaning, aggregation, forecasting, anomaly
detection, growth/Pareto/moving-average, correlation/scatter/treemap,
text-to-query (grounded), the citation gates, the narrative number gate, and
multi-provider LLM dispatch. LLM calls are mocked or offline throughout.

## Sample data

```bash
cd backend && .venv/Scripts/python scripts/make_sample_data.py
```
Generates a 24-month multi-branch dataset (with a planted trend, a declining
branch, and one anomaly) at `../sample_company_sales.csv` to upload and explore.

## Roadmap (optional next steps)

Next connectors (**database** — Postgres/MySQL — and **SaaS** — Stripe /
QuickBooks / Shopify), Stripe **billing**, scheduled/emailed **PDF reports**
(alerts already ship via webhook), and richer forecasting (ARIMA/Prophet). The
geographic map ships with a
bundled India outline + city coordinates (`src/geo.js`); extend `PLACES` there
for more locations/countries.

**Live-source config:** `IH_ENABLE_SCHEDULER` (default on) runs the background
auto-refresh; `IH_SOURCE_TIMEOUT` bounds each fetch; `IH_ALLOW_PRIVATE_FETCH`
opts in to internal URLs (off by default — see the SSRF note above).
