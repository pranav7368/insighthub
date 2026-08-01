# Subprocessors — {{PRODUCT_NAME}}

**Last updated {{LAST_UPDATED}}**

A subprocessor is a third party that may handle customer data on our behalf.
This list is referenced by our [DPA](DPA.md); we will give customers notice
before adding one.

**Keep this list true.** A subprocessor list that omits a service you actually
use is a contractual breach, and it is the first thing a security reviewer
checks against your configuration.

---

## Always in use

| Provider | Purpose | Data handled | Location |
|---|---|---|---|
| {{HOSTING_PROVIDER}} | Hosting and storage | All customer data at rest | {{DATA_LOCATION}} |

## In use only when the corresponding feature is enabled

| Provider | Enabled by | Purpose | Data handled |
|---|---|---|---|
| {{LLM_PROVIDER}} | `IH_LLM_PROVIDER` set (off in offline mode) | Interpreting plain-English questions | The question text and the workspace **schema** — column names and a sample of category values. **Not the rows.** The provider proposes a query; it never returns a number |
| {{PAYMENT_PROCESSOR}} | Billing enabled | Subscriptions and payment | Billing contact and payment details. We never receive card numbers |
| {{ERROR_TRACKING}} | `IH_ERROR_DSN` set | Diagnosing errors | Stack traces and request metadata. Credentials are redacted and row data is never logged |
| {{EMAIL_PROVIDER}} | SMTP configured | Sending email | Recipient address and message content |

If a row above reads `none`, that feature is switched off and no data reaches
any such provider.

## Not subprocessors

Two things send data outward but are **not** our subprocessors, because you
choose them and point them wherever you like:

* **Data source URLs** you connect for syncing — we fetch from where you say.
* **Alert webhooks** you configure — we post a measure name and value to the
  address you give us.

## Self-hosting

If you run {{PRODUCT_NAME}} on your own infrastructure, the hosting row does
not apply to you, and the optional rows apply only where you configure them.
In offline mode, with billing and error tracking off, **no customer data leaves
your deployment**.

## Changes

We will publish changes here and notify customers as set out in the DPA. To be
told about changes, write to {{PRIVACY_EMAIL}}.
