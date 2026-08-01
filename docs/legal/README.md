# Legal pack — drafts, and how to use them

**These are drafts, not legal advice, and not ready to publish.** They were
written to be *factually accurate about what InsightHub actually does* — which
is the part a downloaded template always gets wrong — but the legal judgement
in them has not been reviewed by a lawyer. Have counsel familiar with India's
DPDP Act (and GDPR, if you sell into the EU) review them before they go on a
website or into a contract.

The goal here is to make that review **cheap and short**, not to skip it. A
lawyer reading these is checking wording and risk allocation, not discovering
what your product does with data.

---

## How it fits together

```
company.json          ← the only file you normally edit
templates/*.md        ← the documents, with {{TOKENS}}
scripts/build_legal.py← renders templates + company.json → build/
build/*.md            ← the publishable output (git-ignored)
```

Change a fact once in `company.json` and every document updates. Nothing drifts
out of sync, which is the usual way legal pages go stale and become untrue.

```bash
python scripts/build_legal.py          # render into docs/legal/build/
python scripts/build_legal.py --check  # fail if anything is unfilled
```

`backend/tests/test_legal_pack.py` runs that check in CI, so a document with a
`TODO` in it cannot be published by accident.

---

## Before you publish — the things only you can decide

1. **Fill every `TODO` in `company.json`.** Registered name, address, contact
   addresses, jurisdiction, hosting region.
2. **Name a grievance officer.** India's IT Rules require a named person with
   contact details published. This is a legal requirement, not a nicety.
3. **Decide your retention periods and configure them.** The documents state
   whatever is in `company.json`; the product enforces whatever is set in
   Access & privacy → Retention. **These two must match.** Stating a period you
   do not enforce is worse than stating none.
4. **Confirm the subprocessor list** in `SUBPROCESSORS.md` against what you
   have actually enabled. If `IH_LLM_PROVIDER` is set, that provider is a
   subprocessor. If billing is on, Stripe is. If `IH_ERROR_DSN` is set, that
   service is.
5. **Have counsel review.** Particularly the liability cap, indemnities, and
   the DPA's international-transfer clauses.

## Things these documents deliberately do not say

* **No compliance claims.** They say we provide controls that *support* DPDP
  and GDPR compliance. They never say "we are compliant" — compliance is a
  property of an organisation and an audit, and claiming it without one is both
  false and the fastest way to lose an enterprise deal.
* **No SOC 2 / ISO claims.** There is no report. Do not add one until there is.
* **No security guarantees.** "Reasonable safeguards", which is the standard
  the law actually uses, not "your data is 100% secure".
* **No uptime promise.** Add an SLA only when you can meet it and measure it.

## When to revisit

* whenever a subprocessor is added or removed — a DPA usually obliges you to
  give customers notice of this;
* when retention periods change;
* when you start selling into a new jurisdiction;
* after any change to what data leaves the deployment (a new connector, email,
  telemetry).

`docs/SECURITY.md` holds the technical facts these documents describe. If the
two ever disagree, `docs/SECURITY.md` is the one that reflects the code — fix
the legal document, not the other way round.
