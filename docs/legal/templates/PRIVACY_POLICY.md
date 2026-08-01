# Privacy Policy — {{PRODUCT_NAME}}

**Effective {{EFFECTIVE_DATE}} · Last updated {{LAST_UPDATED}}**

{{COMPANY_LEGAL_NAME}} ("we", "us") operates {{PRODUCT_NAME}}, a business
analytics service. This policy explains what personal data we handle, why, and
what you can ask us to do about it.

We act in two different roles, and the difference matters:

* For **your account** — your name, email, and what you did in the product — we
  are the **data fiduciary** (controller). This policy governs that.
* For **the data you upload** into your workspace, we are a **data processor**
  acting on your instructions. You decide what goes in and why. Our handling of
  it is governed by the Data Processing Agreement, not by this policy.

---

## 1. What we collect

**Account data.** Your email address, a hashed password, your role, and the
workspace you belong to. Passwords are stored using bcrypt; we never see or
store the plaintext.

**Activity data.** An audit record of significant actions — signing in,
uploading data, changing access rules, exporting data — recording who did what
and when. This exists so that you and we can investigate a security incident.

**Technical data.** For each request: the time, the endpoint, the response
status, how long it took, and a request identifier. **We do not log the
contents of your data**, and credentials are redacted before anything is
written.

**Payment data** (if you subscribe). Handled by {{PAYMENT_PROCESSOR}}. We
receive the subscription status and never see your card number.

**The data you upload.** Spreadsheets and documents you choose to add. We do
not inspect them beyond what is needed to build your dashboards and answer your
questions. If they contain personal data about other people, you are the
fiduciary for it — see §7.

## 2. Why we handle it, and on what basis

| Purpose | Basis |
|---|---|
| Providing the service you signed up for | Performance of a contract |
| Keeping accounts secure (audit log, login limits, second factor) | Legitimate interest in security; legal obligation |
| Billing | Performance of a contract |
| Responding to support requests | Performance of a contract |
| Meeting legal obligations, including breach reporting | Legal obligation |

We do **not** sell personal data, do not share it for advertising, and do not
use your uploaded data to train any AI model.

## 3. Who else sees it

Only the providers listed in our [subprocessor list](SUBPROCESSORS.md). In
summary:

* **{{HOSTING_PROVIDER}}** hosts the service.
* **{{PAYMENT_PROCESSOR}}** processes payments, where billing is enabled.
* **{{LLM_PROVIDER}}** — if an AI provider is configured, then when you ask a
  question in plain English, the **question text and your schema** (column
  names, and a sample of category values used to interpret what you asked) are
  sent to it so it can propose a query. **The rows of your data are not sent**,
  and the provider never produces a number: it proposes a query which our
  system validates and runs itself. If the service runs in offline mode, no
  external AI provider is contacted at all.
* Anything you configure yourself — a data source URL to sync from, or a
  webhook to send alerts to — receives data because you asked it to.

We do not otherwise disclose personal data except where the law requires it.

## 4. Where it is stored

{{DATA_LOCATION}}, with {{HOSTING_PROVIDER}}. Where a subprocessor is outside
{{COMPANY_COUNTRY}}, transfers are made under the safeguards described in the
subprocessor list.

## 5. How long we keep it

* **Account data**: for as long as your account exists.
* **Audit records**: {{RETENTION_AUDIT_DAYS}}.
* **Uploaded data**: {{RETENTION_DATA_DAYS}}. You can delete it yourself at any
  time.
* **After you close your account**: we delete your workspace and its data
  within {{RETENTION_AFTER_TERMINATION_DAYS}} days, except where we must keep
  records to meet a legal obligation.

Where your workspace has retention periods configured, the service enforces
them automatically.

## 6. Your rights

You may:

* **see what we hold** — the product will export your own record as a file, in
  Account & security → Download my data;
* **correct** anything inaccurate;
* **delete** your account and its data;
* **withdraw consent** where we relied on it;
* **complain** — to us first, at {{PRIVACY_EMAIL}}, and then to the Data
  Protection Board of India, or your supervisory authority if you are in the
  EU/UK.

We answer requests within 30 days. We may ask you to verify your identity
first, because handing your data to someone impersonating you would itself be a
breach.

**Grievance Officer** ({{COMPANY_COUNTRY}}): {{GRIEVANCE_OFFICER_NAME}},
{{GRIEVANCE_OFFICER_EMAIL}}.

## 7. If you upload other people's data

You remain responsible for it. You must have a lawful basis to hold it and to
put it into {{PRODUCT_NAME}}, and you must tell those people what you are
doing, as their fiduciary. We handle it only on your instructions.

To help you, the product can detect columns that look like personal data —
email addresses, phone numbers, identity numbers, names — and mask them for
everyone except workspace admins. This is a tool, not a substitute for your own
obligations.

## 8. Children

{{PRODUCT_NAME}} is a business tool and is not directed at children. We do not
knowingly collect data from anyone under 18. Under the DPDP Act, processing a
child's data requires verifiable parental consent; do not upload children's
data without it.

## 9. Security

We apply the safeguards described in our [security overview](../SECURITY.md):
tenant isolation, role-based access, row-level restrictions, PII masking,
encryption in transit, audit logging, and optional two-factor authentication.

No service can promise perfect security, and we do not. If a personal data
breach occurs, we will notify the Data Protection Board and affected
individuals as the law requires, and affected customers without undue delay.

## 10. Changes

We will post any change here and update the date above. If a change materially
affects you, we will tell you before it takes effect.

## 11. Contact

{{COMPANY_LEGAL_NAME}}
{{COMPANY_ADDRESS}}
Privacy: {{PRIVACY_EMAIL}} · Security: {{SECURITY_EMAIL}} · General:
{{CONTACT_EMAIL}}
