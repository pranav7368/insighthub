# What to do next

A checklist for the human, in order. Each phase is finishable in a sitting;
don't start a later phase until the earlier one is actually done, because the
later ones assume it.

---

## Phase 1 — Land the work (today, ~30 min)

The branch `feat/templates-arrange-onboarding` has 20 commits and is pushed.
**CI has never run** — the workflow triggers on pull requests and on pushes to
`main`, and this branch has neither. Opening the PR is what first exercises it.

- [ ] **Open the PR.**
      https://github.com/pranav7368/insighthub/pull/new/feat/templates-arrange-onboarding
- [ ] **Watch the five CI jobs.** Backend (with a real Postgres), grounding
      benchmark, frontend, dependency audit, Docker build.
- [ ] **Expect something to fail.** It has never run. The likely candidates,
      all of which pass locally and are unproven on a clean runner:
      - the Postgres job runs the two tests that *skip* on your machine;
      - `npm ci` on a clean checkout;
      - the two Docker image builds.
- [ ] **Read the benchmark output** in the job log — correctness, grounding and
      abstention are printed. That is the number worth watching release to
      release.
- [ ] **Merge.**

---

## Phase 2 — Use your own product (half a day)

Nobody has used InsightHub as a *user*. Tests and I have exercised it; that is
not the same thing, and this is the cheapest bug-finding you will ever do.

- [ ] Run it: `docker compose up --build` → http://localhost:8080
- [ ] Sign up as a brand-new user and **let the tour run**. Does the first
      minute make sense?
- [ ] Load each of the five industry templates. Do the numbers look sane? Does
      any dashboard look wrong or empty?
- [ ] **Upload your own real data** — something messy, not a sample.
- [ ] Ask it five questions you actually care about. **Open "Show SQL" every
      time** and check the query answers the question you asked.
- [ ] Try to break the grounding: ask for a column that does not exist, a
      region that does not exist, something ambiguous. It should refuse.
- [ ] Arrange the dashboard, save a view, share a link, open the link in a
      private window.
- [ ] Write down every irritation. That list is your real roadmap — better than
      anything in `STRATEGY.md`, because it comes from use.

---

## Phase 3 — Prove you can operate it (half a day)

- [ ] **Take a backup and restore it.** Not the CI test — do it by hand, so you
      have done it once before you need to:
      ```bash
      python scripts/backup.py create /backups/insighthub
      python scripts/backup.py verify /backups/insighthub/<folder>
      ```
- [ ] Put the backup on a **schedule**, and `verify` on a schedule too.
- [ ] Confirm the backup destination is **encrypted** and access-restricted.
      An archive on an unencrypted disk undoes the rest of the security work.
- [ ] Deploy somewhere real, with:
      - `IH_ENV=production`
      - `IH_SECRET_KEY` from `python -c "import secrets; print(secrets.token_urlsafe(48))"`,
        stored in a secret manager, **not** in a committed `.env`
      - `IH_CORS_ORIGINS` set to your real frontend origin
      - `IH_DATABASE_URL` pointing at Postgres (not the DuckDB file)
      - HTTPS terminated by a reverse proxy, and `IH_TRUST_PROXY=1`
- [ ] Check `/api/ready` returns `{"status":"ready","backend":"postgres"}`.
- [ ] Decide your **retention periods** and set them in Access & privacy →
      Retention. Preview before saving.

---

## Phase 4 — Put it in front of people (the important one)

Everything above is preparation. This is the part that tells you whether the
product is real.

- [ ] Find **three to five people** who actually have a spreadsheet problem.
      Not friends being polite — people with the problem.
- [ ] Watch them use it without helping. Where they hesitate is a bug.
- [ ] Measure the four numbers from `docs/STRATEGY.md` §6:
      1. time from signup to first real dashboard (target: under 5 minutes)
      2. benchmark accuracy and abstention rate, per release
      3. **what fraction of AI answers had "Show SQL" opened**
      4. security questionnaires passed without an exception
- [ ] **Number 3 is the one that matters.** The entire product thesis is that
      verifiability is worth paying for. If nobody ever opens Show SQL, the
      thesis is wrong or the framing is wrong, and you want to learn that from
      five users rather than after a year of building.

---

## Phase 5 — Before you charge anyone money

- [ ] **Legal pack.** Fill `docs/legal/company.json`, then have a lawyer who
      knows DPDP review the drafts. Until then `--dev` renders readable pages
      for demos. See `docs/legal/README.md`.
- [ ] **Name a grievance officer** with published contact details. Required
      under the Indian IT Rules — a legal requirement, not a nicety.
- [ ] Make the retention periods you *publish* match the ones you *configured*
      in Phase 3.
- [ ] Confirm the subprocessor list matches what you actually have switched on
      (LLM provider, Stripe, error tracking).
- [ ] Fill in the incident-response contact table in
      `docs/legal/templates/INCIDENT_RESPONSE.md`. A runbook with TODOs in the
      contacts is a runbook that fails on the night it is needed.
- [ ] Read `docs/SECURITY.md` §6 (Known Gaps) end to end and decide which you
      are comfortable selling with. They are listed so you are never surprised
      by a customer's reviewer.

---

## What is deliberately NOT on this list

Warehouse connectors, SSO/SCIM, embedded analytics, ML forecasting. They are
real gaps, and `docs/STRATEGY.md` argues they are the wrong next thing: they
are multi-month, well defended by incumbents, and off-thesis until the position
in Phase 4 is won.

Revisit that judgement when a real customer names one of them as the reason
they cannot buy — not before.
