# InsightHub data API

Every number in the app comes from the same HTTP API the app itself uses, so anything you can see
on a dashboard you can fetch from a script, a BI tool or a scheduled job. The full, always-current
reference is the OpenAPI schema your deployment serves at `/docs` (interactive) and
`/openapi.json`. This page covers authentication and the calls most integrations need.

## Authentication

An **admin** creates a key under **API keys** in the sidebar. The key is shown once; store it in
your secret manager. Send it as a bearer token:

```bash
curl -H "Authorization: Bearer ihk_…" https://your-host/api/datasets
```

What a key can do:

| | Read data ("viewer") | Read and write data ("editor") |
|---|---|---|
| List datasets, dashboards, drill, variance, rows, CSV export, Ask | ✓ | ✓ |
| Upload / append data, save views, targets, alerts, reports, share links | — | ✓ |
| Team, billing, privacy, security settings, other API keys | — | — |

And what it is bounded by:

* **It acts as the admin who created it.** That person's row rules apply to every number it reads.
  If they are demoted, the key is demoted with them; if they leave the workspace, the key stops
  working.
* **Personal data is always masked** for a key, even one an admin made: masking is waived only for
  a person signed in to the app.
* **Expiry and revocation take effect immediately.** An unknown, wrong, expired or revoked key all
  get the same `401`.

Only a SHA-256 of the key's secret is stored. Keys are listed by a hint (`ihk_<id>_…`) with their
creator, role, creation, last use and expiry. Creating and revoking keys is recorded in the audit
log.

## Common calls

All paths are under `/api`. Responses are JSON unless noted.

| Call | What it returns |
|---|---|
| `GET /datasets` | Your datasets: id, name, row count |
| `GET /datasets/{id}/dashboard?measure=revenue&date_from=2026-01&date_to=2026-06&region=North` | KPIs, breakdowns, trend, forecast, insights — exactly what the dashboard shows, for that scope |
| `GET /datasets/{id}/inspect?measure=revenue&filters={"region":"North"}` | One number, with its SQL, row count, trend, comparison and contributors |
| `GET /datasets/{id}/variance?measure=revenue` | Why the latest period changed: a reconciling waterfall by the most concentrated dimension |
| `GET /datasets/{id}/rows?filters=…&page=1` | The rows behind a number (masked where the dataset has personal data) |
| `GET /datasets/{id}/export.csv` | The dataset as CSV |
| `POST /datasets/{id}/query` `{"question": "revenue by region last quarter"}` | A grounded answer with the SQL that produced it, or an explicit "I can't answer that" |
| `POST /datasets/{id}/append` (multipart `file`) | Append rows from a CSV/Excel file (editor keys) |

`filters` is a JSON object of `column: value`, URL-encoded. Dates are `YYYY-MM` or `YYYY-MM-DD`.

## Limits and errors

* Requests are rate-limited per client IP; over the limit you get `429` with `Retry-After`.
* `401` — no key, or the key is not valid now. `403` — valid key, but not allowed to do this
  (wrong role, or an account/team/billing/privacy endpoint). `404` — not found *in your workspace*.
* Error bodies are `{"detail": "…"}` and safe to show to a person.
