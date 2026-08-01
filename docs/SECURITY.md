# Security & data protection

What is built, what is the operator's job, and what is not done yet. Written to
be handed to a customer's security reviewer without editing.

**Read this first:** InsightHub provides technical controls that *support*
GDPR and India's DPDP compliance. It is not "compliant" software and cannot be
— compliance is a property of an organisation and an audit, not of a codebase.
Anyone claiming otherwise in a sales conversation is creating a liability.

---

## 1. Controls in the product

| Control | How it works | Where |
|---|---|---|
| **Tenant isolation** | `workspace_id` comes from the verified JWT and is never accepted from client input; every query is scoped by it | `api/deps.py` |
| **SQL injection defence** | Identifiers are whitelisted against the dataset's real columns and quoted; values are always bound parameters. No user text is ever formatted into SQL | `core/sqlsafe.py` |
| **Row-level security** | Per-member row rules rewrite the table reference into a filtered subquery shared by every read path; fails closed if a rule's column disappears | `analytics/rls.py` |
| **PII masking** | Sensitive columns detected on upload by name and value shape, redacted in the SQL projection for everyone except admins; source data never altered | `analytics/privacy.py` |
| **RBAC** | admin / editor / viewer; content mutations require editor, user and policy management require admin | `api/deps.py` |
| **Password policy** | NIST SP 800-63B style: length, breach-corpus blocklist, no account-derived or sequential passwords | `core/passwords.py` |
| **Session revocation** | `token_epoch` per user; bumped on password change, role change, and "sign out everywhere" | `core/security.py` |
| **Login lockout** | Per account (not just per IP), 8 failures → 15 minutes; identical 401 for every failure so account existence is not disclosed | `main.py` |
| **Two-factor auth** | TOTP (RFC 6238) on the standard library, verified against the RFC's own test vectors; replay of a code inside its window refused; single-use recovery codes stored hashed | `core/mfa.py` |
| **Workspace MFA requirement** | An admin can require a second factor for every member; enforced in `get_principal`, so a new endpoint is covered by default. A member without one may reach MFA setup and nothing else | `api/deps.py` |
| **Audit log** | Every privileged action recorded with actor, action and target | `core/db.py` |
| **Data export / erasure** | Per member and per workspace; erasure drops physical dataset tables and verifies itself | `core/datarights.py` |
| **SSRF defence** | Every outbound URL (connectors, alert webhooks) resolved and checked against private ranges | `core/nettrust.py` |
| **Rate limiting** | Per IP, per category (auth / LLM / general) | `core/ratelimit.py` |
| **Security headers** | `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` | `main.py` |
| **Structured logging** | JSON, request-correlated, credential-redacted; identifiers logged, never row contents | `core/observability.py` |
| **Schema migrations** | Versioned ledger so a released build never meets a database it cannot read | `core/migrations.py` |
| **Backup & restore** | `scripts/backup.py` archives every table to Parquet with a manifest, verifies an archive without restoring it, and refuses an archive from a newer build. The **restore is tested on every CI run** — real data in, wiped, restored, same dashboard number out | `core/backup.py` |
| **Accessibility** | WCAG 2.1 AA: zero axe-core violations across login, dashboard, tour and every admin dialog, in light and dark. Structural rules regression-tested in CI | `frontend/src/a11y.test.jsx` |

Verified by **501 backend tests** and **76 frontend tests**, including a source-guard test that fails
if any module queries a dataset table without going through the row-level
security rewrite.

---

## 2. Encryption

**In transit** — InsightHub does not terminate TLS. Run it behind a reverse
proxy (Caddy, nginx, Traefik, or a cloud load balancer) that does, set
`IH_TRUST_PROXY=1`, and redirect HTTP to HTTPS there. Do not expose the
backend port directly.

**At rest — this is the operator's responsibility, and it is not optional for
an enterprise deal.** The application stores data in one of two places:

* **Postgres** (`IH_DATABASE_URL`) — recommended for production. Encrypt at the
  volume or service layer:
  * managed (RDS / Cloud SQL / Azure Database): enable storage encryption at
    creation; it cannot be turned on afterwards without a restore;
  * self-hosted: use an encrypted volume (LUKS, or the cloud provider's
    encrypted block storage). Postgres has no built-in whole-database
    encryption.
* **DuckDB file** (default, `IH_DB`) — a single file. Encrypt the filesystem or
  volume it lives on. Suitable for single-tenant or evaluation deployments;
  for multi-tenant production use Postgres.

**Backups inherit none of this automatically.** An archive written to an
unencrypted disk undoes the whole control. Encrypt the backup destination and
restrict who can read it.

Use `scripts/backup.py` — it works identically on both storage backends, and
`verify` should run on a schedule, because an archive that cannot be read is
worth discovering on an ordinary Tuesday rather than on the day you need it.

**Key management** — `IH_SECRET_KEY` signs sessions. It must be a real random
value (`python -c "import secrets; print(secrets.token_urlsafe(48))"`), stored
in a secret manager rather than a `.env` committed anywhere, and rotated on
suspicion of exposure. Rotating it invalidates every existing session, which is
the intended behaviour. The app refuses to start in production with the default.

---

## 3. Data flows and subprocessors

Be precise about this; a security reviewer will ask.

* **By default, no data leaves the deployment.** `IH_OFFLINE=1` uses the
  deterministic local analyst; no external LLM is called.
* **If an LLM provider is configured** (`IH_LLM_PROVIDER` + key), then question
  text and *schema* — column names, and sampled dimension values used to
  interpret a question — are sent to that provider. Row-level data is not sent,
  and the provider never produces a number: it only proposes a query intent
  which the app validates and executes itself. **The provider is a subprocessor
  and must appear on the customer-facing list.**
* **Connectors** fetch from URLs the customer configures, through the SSRF
  guard.
* **Alert webhooks** POST a measure name and value to a URL the customer
  configures.
* **Error tracking** (`IH_ERROR_DSN`) is off by default. Turning it on sends
  stack traces to a third party — another subprocessor.

---

## 4. Retention

Configurable per workspace (`core/retention.py`), applied by the scheduler.
Three independent periods: **audit entries**, **rollback archives**, and
**uploaded datasets**.

**Everything is off by default.** `0` means keep forever, and a workspace that
has not configured a period is never touched — silent deletion because someone
shipped a default would be unrecoverable. Each period has a floor (7 days, and
30 for uploaded data) so a mistyped `1` cannot erase a year of history the same
night, and `POST /api/privacy/retention/preview` reports exactly what a sweep
would remove without removing anything, so the blast radius is visible before
the policy is armed.

A sweep records itself in the audit log *before* pruning it, so it cannot erase
its own trace. Sweeps are idempotent and workspace-isolated.

**What you may now state:** whatever periods you have actually configured.
The mechanism exists; the *policy* is still an operator decision, and the
number you publish must match the number set here.

---

## 5. Incident response

DPDP requires notifying the Data Protection Board and affected individuals of a
personal data breach, with a **72-hour** expectation. That clock is far too
short to improvise, so the runbook must exist before it is needed:

1. **Contain** — revoke sessions (`/api/auth/revoke-sessions` per account, or
   rotate `IH_SECRET_KEY` to invalidate all), revoke share links, rotate
   provider keys.
2. **Assess** — which workspaces, which data categories, how many individuals.
   The audit log and request logs are the evidence; preserve them before
   anything is rebuilt.
3. **Notify** — the Board and affected principals within the required window;
   for EU subjects, the supervisory authority within 72 hours of awareness.
4. **Record** — what happened, what was done, what changed as a result.

**Open item — assign the named owner and contact details for each step above.**

---

## 6. Known gaps

Stated plainly, because a reviewer will find them anyway and finding them
undisclosed is worse than finding them listed:

* **No SSO / SCIM.** No enterprise identity provider integration.
* **No SOC 2 report.** Controls exist; an audit and observation window do not.
* **Encryption at rest is deployment-dependent** (§2), not enforced by the app.
* **Single-node storage.** No HA story for the DuckDB deployment mode.

---

## 7. Legal documents

Drafts exist in [`docs/legal/`](legal/README.md): privacy policy, terms of
service, DPA, subprocessor list, and an incident-response runbook. They are
generated from one facts file (`docs/legal/company.json`) so a change updates
every document at once, and they are written to match what the code actually
does — the AI boundary, the real subprocessors, the retention mechanism.

**They have not been reviewed by a lawyer and must not be published until they
are.** They block nothing in the meantime: no application code reads them, and
`python scripts/build_legal.py --dev` renders readable pages from obvious
placeholders for development, which can never satisfy the publish gate. `python scripts/build_legal.py --check` fails while any placeholder
remains, and that check runs in the test suite, so an unfinished draft cannot
reach a website by accident.

What still needs a human: the registered entity details, a named grievance
officer (required under the Indian IT Rules), the retention periods you will
actually configure, and counsel's review of the liability cap, indemnities and
transfer clauses.

---

## Reporting a vulnerability

Email the maintainer with steps to reproduce. Please do not open a public issue
for a security problem. State a disclosure window here once a contact address
and response commitment are agreed.
