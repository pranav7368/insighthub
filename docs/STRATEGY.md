# InsightHub — position, gaps, and the order to fix them

*Last reviewed: 2026-07-31. Rewrite this when the market evidence below stops
being true, not on a schedule.*

---

## 1. The one-line thesis, and why the market just validated it

> Every number is computed from the data and traceable. The AI phrases the
> insight; it never invents the figure.

This is not a nice-to-have position. It is the exact problem the AI-analytics
category has failed to solve, and the 2026 evidence is unusually blunt:

| Finding | Source |
|---|---|
| AI data-analyst tools land at **50–89% accuracy**; multi-table enterprise questions fall to ~50% | [Kaelio](https://www.kaelio.com/blog/how-accurate-are-ai-data-analyst-tools) |
| **86% in the demo, 6% on real data** with the identical model — "accuracy doesn't sit in the model, it sits in the architecture around it" | [oneagent](https://oneagent.de/en/blog/ai-data-analysis-accuracy) |
| dbt benchmark: **84.1% raw text-to-SQL → 100% with a semantic layer** | [Cube](https://cube.dev/articles/best-bi-tools-2026) |
| Hallucinations here are "plausible but incorrect… syntactically valid and well-presented. You do not know it is wrong until someone makes a decision on bad data" | [Mitzu](https://mitzu.io/post/ai-analytics-hallucinations-sql-transparency/) |
| "**SQL transparency and analyst approval** are the practical controls for trustworthy, governed AI analytics" | [Mitzu](https://mitzu.io/post/ai-analytics-hallucinations-sql-transparency/) |

Read that table again. The industry's conclusion — semantic layer, show the
SQL, refuse when you can't answer — **is already the architecture of this
product**: certified metrics, `show-the-SQL` on every answer, the number gate
on AI narrative, and abstention.

So the strategic situation is not "catch up on features." It is:

> **We are early to the right architecture and have not proven it.**
> Competitors assert accuracy. We can *demonstrate* it, per answer and in
> aggregate. Nobody in this category is doing that.

### What that means for the roadmap
Anything that strengthens *provable* trust beats anything that adds another
chart type. The highest-leverage unbuilt thing in this repo is not a feature —
it is a **published, reproducible accuracy benchmark** (§4, P1-A).

---

## 2. Honest competitive read

| Competitor | Where they beat us today | Where we can win |
|---|---|---|
| **ThoughtSpot** (from $25/user/mo) | Brand, scale, Spotter AI agent, enterprise muscle | Fragmented semantic model; premium price; we are radically simpler to adopt |
| **Metabase** (Cloud from $100/mo) | Huge OSS community, connectors, maturity | Weak governance story; AI bolted on rather than grounded |
| **Omni / Sigma / Looker** | Semantic modelling depth, enterprise trust | Require a data team and a warehouse; we work from a spreadsheet in 60 seconds |
| **Hex** | Notebook power for analysts | Not a business-user self-serve product |
| **Julius / Fabi / generic "AI analyst"** | Fast, cheap, viral | Exactly the 6%-on-real-data problem. This is who we beat on trust |

**Where we genuinely have no answer yet:** live warehouse connectors
(Snowflake/BigQuery/Postgres-as-source), embedded analytics, and scale beyond a
single-node DuckDB. Those are real, and they cap deal size — not something to
paper over.

**Honest scoring of "nobody can compete with us anywhere":** not achievable, and
not worth chasing. We will lose to Looker on warehouse-scale modelling and to
Metabase on connector breadth for years. The winnable, defensible position is:

> **The analytics tool a non-technical team can trust with a decision** —
> fastest time-to-dashboard from a file, and the only one that proves its
> numbers.

Own that completely before spending a rupee widening.

---

## 3. What is genuinely strong today

Verified in this repo, not aspirational: multi-tenant isolation from a verified
JWT · SQL-injection defence via identifier whitelisting with bound values ·
SSRF guards on every outbound fetch · certified metrics with show-the-SQL ·
grounded Ask with abstention · number-gated AI narrative · **row-level
security** and **PII masking** enforced at a single relation rewrite with a
source-guard test · roles/invites · share links that inherit their author's
restrictions · plan gating + Stripe · Postgres or DuckDB · Docker one-command
deploy · **322 backend tests**.

That is a stronger security posture than most seed-stage BI products. It is not
yet an *enterprise-sellable* one — §4 explains the difference.

---

## 4. The gap list, in the order that matters

Ordered by "what stops money today", not by interest.

### P0 — Existential. Nothing ships safely until these exist.

**P0-A · Schema migrations.** `db.py` is one `CREATE TABLE IF NOT EXISTS`
block. Adding a column to an existing table **silently does nothing** on any
database that already exists. This was hit twice in a single day's work
(`alerts.created_by`, `column_policies`). Consequence: *you cannot ship an
update to a customer who already has data.* Every other item on this list is
blocked behind it.

**P0-B · CI.** 322 tests that nothing runs automatically will rot within
weeks, and there is no gate stopping a broken commit from reaching `main`.

### P1 — Blocks the first real customer.

**P1-A · The accuracy benchmark.** Per §1 this is also the marketing moat. A
golden-question suite (question → expected SQL shape → expected value) run in
CI, scored, and published. Turns "trust us" into a number we re-earn on every
commit. *No competitor publishes this.*

**P1-B · Enterprise auth.** Password policy is `len >= 8` — no strength rule,
no breach check, no lockout. JWTs cannot be revoked (a fired employee's token
stays valid until expiry). No MFA. All three appear on every security
questionnaire.

**P1-C · Data subject rights + retention.** DPDP's full-compliance deadline is
**13 May 2027**, with 72-hour breach notification, deletion-on-termination, and
stated retention periods ([Fisher Phillips](https://www.fisherphillips.com/en/insights/insights/indias-new-data-privacy-rules-are-here),
[Atlas Systems](https://www.atlassystems.com/blog/digital-personal-data-protection-act-india)).
We have no way to export or erase one person's data, and no retention policy.
GDPR needs the same primitives. Build once, satisfy both.

**P1-D · Encryption at rest.** The DuckDB file and Postgres volume are
unencrypted. "Encrypted at rest and in transit" is a hard checkbox on every
enterprise questionnaire ([Sprinto](https://sprinto.com/blog/soc-2-requirements/)).

### P2 — Blocks scaling the team and the product.

Structured logging + error tracking + metrics (currently zero — production
debugging would be blind) · frontend tests (currently zero) · async ingestion
(large uploads block a worker) · backup/restore runbook · accessibility audit ·
API keys + public API · scheduled email reports.

### P3 — Widening, once the position above is won.

Warehouse connectors · embedded analytics · SSO/SCIM · ML forecasting ·
object storage · i18n.

### Not on the roadmap, deliberately
Chasing Looker on semantic modelling depth. Chasing Metabase on connector
count. Both are multi-year, well-defended, and off-thesis.

---

## 5. Compliance posture — say this, not more

A standing rule for this product's public claims:

* We can say: "InsightHub provides the technical controls that support GDPR and
  DPDP compliance — tenant isolation, RBAC, row-level security, PII masking,
  audit logging, data export and erasure."
* We must **not** say "InsightHub is GDPR/DPDP/SOC 2 compliant." Compliance is
  a property of an organisation and an audit, not of a codebase. SOC 2 Type II
  requires an observation window and an auditor; claiming it without one is
  both false and the fastest way to lose an enterprise deal.
* Every claim in marketing must map to a control in this repo. If it does not,
  delete the claim or build the control.

Also needed before a first paying customer, and none of it exists yet: privacy
policy, terms of service, DPA template, subprocessor list, incident-response
runbook with the 72-hour clock written into it.

---

## 6. How to judge whether this is working

Not vanity metrics. Four numbers:

1. **Time from signup to first real dashboard** (target: under 5 minutes).
2. **Benchmark accuracy + abstention rate** — published, per release.
3. **Percentage of AI answers where the user opened "Show SQL"** — the trust
   feature only matters if it is used; if nobody opens it, the framing is wrong.
4. **Security questionnaires passed without an exception.**

---

## 7. The sequence

1. P0-A migrations, P0-B CI. *Nothing else is safe to build first.*
2. P1-A benchmark — the moat, and it needs CI to be meaningful.
3. P1-B/C/D enterprise auth, data rights, encryption — the deal-blockers.
4. P2 observability and frontend tests — before the team grows.
5. Only then P3.
