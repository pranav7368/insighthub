# InsightHub

**Turn structured business data into an auditable analytics dashboard and an AI-assisted analysis workflow.** InsightHub computes metrics deterministically from source data, then constrains AI-generated narratives to the computed results. It supports configurable hosted or local LLM providers and can run core analytics without an API key.

> **Status:** Portfolio-grade engineering project with passing CI on the current main branch. Validate security, privacy, scalability, and deployment controls before using it with sensitive or production data.

## Why it is different

InsightHub separates deterministic computation from AI-generated explanation to reduce unsupported numerical claims:

- **Dashboards and metrics** use SQL and statistical computations over the uploaded data.
- **Conversational analysis** converts questions into validated query plans; the model selects permitted fields while the application executes the query and calculates the result.
- **AI-assisted narratives** receive computed facts rather than unrestricted raw rows, and a number gate flags figures that are not present in those facts.
- **Abstention paths** allow the workflow to avoid guessing when the available data cannot support an answer.

## Technology

- **Backend:** Python, FastAPI
- **Frontend:** React
- **Data:** PostgreSQL
- **Infrastructure:** Docker and GitHub Actions
- **AI integration:** Configurable hosted or local LLM providers

## Engineering focus

- Clear separation between deterministic analytics and generated explanation
- Traceable, data-backed metrics
- Provider-flexible AI integration
- Containerized local development
- Automated checks through continuous integration

## Analysis workflow

Every figure on the dashboard can be opened and traced back to its source:

- **Drill-down:** select any metric or chart element to see how it is calculated (a plain-language formula and the executed SQL), its trend at different time grains, its largest contributors, and the underlying rows. Drill paths are kept in the URL, so they can be revisited or shared.
- **Change analysis:** a period-over-period change is broken into contributions that sum to the total, compared over matching date ranges when the latest period is incomplete, and labelled by how unusual it is relative to the series' typical variation.
- **Targets and alerts:** a target can be set for a measure and period; progress is projected from the current run rate, and an optional webhook alert fires when that projection falls below a chosen threshold.
- **Recommended actions:** rule-based prompts (for example, a declining segment or a dependency on a single value) are shown with the figures behind them and a link to the supporting data.

Row-level access rules and PII masking apply to every drill-down path, including exported rows.

## Responsible-use notes

InsightHub is an engineering portfolio project, not a guarantee of analytical correctness or production security. Outputs should be reviewed against source data. Do not upload confidential or regulated data until the deployment, access controls, retention policy, and privacy requirements have been independently validated.
