# Incident response runbook — {{PRODUCT_NAME}}

**Internal.** Not published. Last updated {{LAST_UPDATED}}.

A personal data breach starts a clock you cannot pause: the DPDP Rules expect
notification of the Data Protection Board, and GDPR requires a supervisory
authority within **72 hours of awareness**. Our DPA commits us to telling
affected customers within **48 hours** so they can meet their own deadline.

That is far too short to work out who does what. Decide it now.

---

## Who does what

| Role | Person | Reachable at |
|---|---|---|
| Incident lead — decides, and owns the clock | {{GRIEVANCE_OFFICER_NAME}} | {{GRIEVANCE_OFFICER_EMAIL}} |
| Technical lead — contains and investigates | TODO | TODO |
| Customer communications | TODO | TODO |
| Legal counsel | TODO | TODO |

> Fill these in. A runbook with TODOs in the contact table is a runbook that
> fails on the night it is needed.

**The clock starts when we become *aware*, not when we finish investigating.**
Note the time in UTC, in writing, immediately.

---

## 1. Contain — first hour

Do not rebuild anything yet: rebuilding destroys the evidence you will need.

- [ ] Note the time of awareness and open an incident log. Every action, with a
      timestamp, from here on.
- [ ] **Preserve evidence first** — copy the audit log and request logs
      somewhere the incident cannot reach.
- [ ] Scope it: which workspaces, which data, how many people.
- [ ] Contain, choosing the smallest effective action:
  - a single compromised account → `POST /api/auth/revoke-sessions`, force a
    password reset;
  - suspected token compromise across the board → rotate `IH_SECRET_KEY`, which
    invalidates **every** session at once;
  - a leaked share link → revoke it in Manage → Share dashboard;
  - a compromised provider key → rotate it at the provider and in config;
  - active exploitation → take the service offline. An outage is recoverable;
    a continuing breach is not.

## 2. Assess — first day

- [ ] What data was involved? Account data, uploaded customer data, or both?
- [ ] Was it personal data? If yes, the notification duties below apply.
- [ ] Whose? Which customers, and roughly how many individuals each.
- [ ] How did it happen, and is the hole closed?
- [ ] Could it still be happening?

Write the answers down as you go. The regulator will ask for exactly this, and
memory a week later is not evidence.

## 3. Notify

**Customers — within 48 hours of awareness** (our DPA commitment). They cannot
meet their own 72-hour duty if we are slow. Send what we know rather than
waiting for a complete picture, and say plainly that it is preliminary:

> What happened · what data · when · what we have done · what they should do ·
> who to contact · when we will update them next.

**Regulators**
- Data Protection Board of India — as the DPDP Rules require.
- EU/UK supervisory authority — within 72 hours of awareness, where GDPR
  applies and the breach is likely to risk people's rights.

**Individuals** — where the risk to them is high, without undue delay. In our
processor role this is usually the customer's duty; help them do it.

Counsel reviews anything that goes outside before it goes.

## 4. Afterwards — within two weeks

- [ ] Write the post-mortem: timeline, root cause, what worked, what did not.
- [ ] **No blame.** People hide incidents from processes that punish them, and a
      hidden incident is the expensive kind.
- [ ] Fix the root cause, and add the test that would have caught it.
- [ ] Update this runbook with whatever it got wrong.
- [ ] Keep the incident record — you may need to show it.

---

## Rehearse it

A runbook nobody has read does not work. Once a quarter, take 30 minutes and
talk through a scenario:

* an admin's laptop is stolen, unlocked;
* a member reports seeing another workspace's data;
* a share link appears in a public search index;
* the AI provider discloses a breach on their side.

For each: who notices, how, what is the first action, who is told, and by when?

## What is *not* a personal data breach

Availability alone — a crash, an outage, a failed deploy — is not a personal
data breach unless data was lost or exposed. Run it as an ordinary incident.
Keep the two paths separate so the serious one keeps its urgency.
