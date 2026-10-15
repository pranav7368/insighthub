# What to do next

A checklist for the human, in order. Each phase is finishable in a sitting;
don't start a later phase until the earlier one is actually done, because the
later ones assume it.

---

## Phase 1 — Land the work (today, ~30 min)

PR #2 (`feat/drill-inspector`) carries the pro-analyst layer: drill into any
number, "why it changed", targets, recommended actions, the right-click menu
and Ctrl/⌘ K. All five CI jobs are green, including the backend against a real
Postgres (which is what proves migration `0009_targets` on that backend).

- [ ] **Read the one behaviour change before merging:** clicking a bar or a
      slice now opens its details instead of filtering the dashboard. The
      panel's "Show this on the dashboard" does the filtering. If your users
      are used to click-to-filter, say so in the release note.
- [ ] **Skim the PR description** — it lists every new endpoint and what each
      commit does, so the review can go commit by commit.
- [ ] **Read the benchmark output** in the CI log — correctness, grounding and
      abstention. That is the number worth watching release to release.
- [ ] **Merge** https://github.com/pranav7368/insighthub/pull/2

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
- [ ] **Drill all the way down once:** click a KPI → a contributor → another
      contributor → a month on its trend → Records. Then press the browser's
      back button and check it walks back up one level at a time. Copy the URL
      into a private window: it should reopen the same drill.
- [ ] Open **Why it changed** on a number that dropped. Do the waterfall steps
      add up to the change? Does the significance label match your gut?
- [ ] **Set a target** for this month and watch the KPI card show its pace.
      Check the projection by hand (actual ÷ days so far × days in month).
- [ ] Read the **Recommended actions** and open the evidence for each. Is any
      of them something you would *not* act on? That is a rule to tune.
- [ ] Right-click a bar; press Ctrl/⌘ K and type a region or product name.
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
