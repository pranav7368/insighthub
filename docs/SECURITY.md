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
| **Audit log** | Every privileged action recorded with actor, action and target | `core/db.py` |
| **Data export / erasure** | Per member and per workspace; erasure drops physical dataset tables and verifies itself | `core/datarights.py` |
| **SSRF defence** | Every outbound URL (connectors, alert webhooks) resolved and checked against private ranges | `core/nettrust.py` |
| **Rate limiting** | Per IP, per category (auth / LLM / general) | `core/ratelimit.py` |
| **Security headers** | `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` | `main.py` |
| **Structured logging** | JSON, request-correlated, credential-redacted; identifiers logged, never row contents | `core/observability.py` |
| **Schema migrations** | Versioned ledger so a released build never meets a database it cannot read | `core/migrations.py` |

Verified by **426 backend tests** and **57 frontend tests**, including a source-guard test that fails
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

**Backups inherit none of this automatically.** A `pg_dump` written to an
unencrypted disk undoes the whole control. Encrypt backups and restrict who can
read them.

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

The product does not currently expire anything automatically. Uploaded data,
audit entries and archived rows persist until deleted. Under DPDP the retention
period must be *stated* and honoured, so an operator must either document a
policy and apply it, or implement scheduled deletion before making a retention
claim.

**Open item — do not claim a retention policy until this is built.**

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
* **MFA is not enforceable workspace-wide.** Members may enable it; an admin
  cannot yet require it for everyone, which some questionnaires ask for.
* **No automated retention or scheduled deletion** (§4).
* **No SOC 2 report.** Controls exist; an audit and observation window do not.
* **Encryption at rest is deployment-dependent** (§2), not enforced by the app.
* **Single-node storage.** No HA story for the DuckDB deployment mode.
* **Backups are the operator's job** — no automated backup or tested restore.

---

## 7. Legal documents still required

None of these exist yet, and all are needed before a first paying customer:

* privacy policy (what is collected, why, retention, subject rights)
* terms of service
* data processing agreement (DPA) — customer is controller, you are processor
* subprocessor list (§3), with a change-notification commitment
* incident response contacts (§5)

These need a lawyer familiar with DPDP and, if selling into the EU, GDPR. The
technical facts they must describe are in this document; the legal drafting is
not something to improvise from a template.

---

## Reporting a vulnerability

Email the maintainer with steps to reproduce. Please do not open a public issue
for a security problem. State a disclosure window here once a contact address
and response commitment are agreed.
