# Data Processing Agreement — {{PRODUCT_NAME}}

**Effective {{EFFECTIVE_DATE}}**

This Agreement forms part of the Terms of Service between {{COMPANY_LEGAL_NAME}}
("Processor", "we") and the customer ("Controller", "you"), and governs our
handling of personal data you put into {{PRODUCT_NAME}}.

Under India's Digital Personal Data Protection Act, 2023 you are the **Data
Fiduciary** and we are a **Data Processor**. Under GDPR the equivalent terms are
Controller and Processor. Where the two regimes differ, the stricter applies.

---

## 1. What we process, and why

| | |
|---|---|
| **Subject matter** | Providing the {{PRODUCT_NAME}} analytics service |
| **Duration** | For as long as your account is active, plus the deletion window in §7 |
| **Nature and purpose** | Storing, querying, aggregating and displaying data you upload; answering questions about it |
| **Categories of data** | Whatever you choose to upload. Typically business records; may include personal data about your customers or staff |
| **Categories of data subject** | Determined by you |

We do not decide what you upload, and we do not use it for our own purposes.

## 2. Our obligations

We will:

1. **Process only on your documented instructions** — using the product is your
   instruction. If we believe an instruction breaks the law, we will tell you
   rather than carry it out.
2. **Keep it confidential.** Anyone with access is bound by confidentiality.
3. **Apply the safeguards in [our security overview](../SECURITY.md)** —
   tenant isolation, role-based access, row-level restrictions, PII masking,
   encryption in transit, audit logging, optional two-factor authentication.
4. **Not sell your data, and not use it to train AI models.**
5. **Help you answer data subject requests** (§5).
6. **Tell you about a breach without undue delay** (§6).
7. **Delete or return your data when we are done** (§7).
8. **Make available the information you need** to verify the above, and allow
   an audit as set out in §8.

## 3. Your obligations

You will:

1. have a lawful basis for the personal data you upload, and give the required
   notices to the people it concerns;
2. not upload special-category or children's data unless you have the
   additional basis the law requires;
3. configure access correctly — roles, row-level rules, and PII masking are
   yours to set;
4. keep your credentials secure, and enable two-factor authentication where
   appropriate.

**You control the retention periods.** Where you set them, the service enforces
them. Where you do not, data is retained until you delete it.

## 4. Subprocessors

You give us general authorisation to use the subprocessors listed at
[SUBPROCESSORS.md](SUBPROCESSORS.md). We will give you at least **30 days'
notice** before adding one, and you may object on reasonable data-protection
grounds; if we cannot resolve your objection, you may terminate the affected
service without penalty for the unused remainder of your term.

Each subprocessor is bound by terms no less protective than these.

Note that our AI subprocessor receives **question text and schema only, never
your rows**, and that in offline mode no AI subprocessor is used at all.

## 5. Data subject requests

The product lets you export and delete data yourself:

* export a member's record, or the whole workspace, as JSON;
* erase a member, or erase the workspace and all of its data.

Where you need more, we will assist within **10 business days**. If a data
subject contacts us directly, we will refer them to you rather than act.

## 6. Personal data breach

We will notify you **without undue delay, and in any event within 48 hours** of
becoming aware of a personal data breach affecting your data, so that you can
meet your own reporting deadlines — the DPDP Rules expect notification of the
Data Protection Board, and GDPR requires notification of a supervisory
authority within 72 hours of *your* awareness.

Our notice will describe what happened, the categories and approximate volume
affected, the likely consequences, and what we have done. Where we do not yet
know everything, we will send what we have and follow up rather than wait.

We will not make any public statement identifying you without your consent
unless we are legally required to.

## 7. Deletion and return

On termination, or on your written request:

* you may export your workspace at any time before deletion;
* we delete your workspace and its data — including the physical database
  tables holding your uploaded rows — within
  **{{RETENTION_AFTER_TERMINATION_DAYS}} days**;
* backups are overwritten on their normal cycle, and remain protected by this
  Agreement until they are.

We keep only what a legal obligation requires us to keep.

## 8. Audit

We will answer reasonable written questions about our processing, and provide
whatever certifications and reports we hold. You may audit no more than once a
year (or after a breach affecting you), on 30 days' notice, at your cost,
during business hours, without disrupting other customers.

**We do not currently hold a SOC 2 or ISO 27001 report.** We would rather say so
than imply otherwise.

## 9. International transfers

Customer data is stored in {{DATA_LOCATION}}. Where a subprocessor processes
data outside that region, the transfer relies on the safeguards recorded in the
subprocessor list — Standard Contractual Clauses where GDPR applies, and any
mechanism required under {{COMPANY_COUNTRY}} law.

## 10. Liability

Liability under this Agreement is subject to the limits in the Terms of
Service, except where the law does not permit that limit.

## 11. Conflicts

If this Agreement conflicts with the Terms of Service, this Agreement governs
for matters of personal data.

---

**{{COMPANY_LEGAL_NAME}}**
{{COMPANY_ADDRESS}}
Privacy contact: {{PRIVACY_EMAIL}}
