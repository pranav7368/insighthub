// The first-run product tour.
//
// Steps are declarative and anchored to `data-tour` attributes. A step whose
// target is not on screen is skipped automatically, so the same script works
// for a brand-new empty workspace and for one that already has a dashboard —
// no branching, no separate "empty state" tour to keep in sync.

export const TOUR_KEY = "ih_tour_v1";

export const TOUR_STEPS = [
  {
    id: "welcome",
    title: "Welcome to InsightHub",
    body: "A dashboard and an AI analyst for any spreadsheet you have. The rule that makes it different: every number you see is computed from your data — the AI phrases the insight, it never invents the figure.",
  },
  {
    id: "upload",
    target: '[data-tour="upload"]',
    title: "Bring your data",
    body: "Drop in a CSV or Excel file and the dashboard builds itself — measures, dimensions and dates are detected for you. PDFs and Word docs become searchable in the Ask tab.",
  },
  {
    id: "connect",
    target: '[data-tour="connect"]',
    title: "…or keep it live",
    body: "Connect a Google Sheet or a CSV link and InsightHub re-syncs it on a schedule, so the dashboard stays current without another upload.",
  },
  {
    id: "templates",
    target: '[data-tour="templates"]',
    title: "Start from your industry",
    body: "Not ready to upload? Pick a template — retail, SaaS, e-commerce, logistics or healthcare — and get realistic data with the metrics that industry actually reports on.",
  },
  {
    id: "kpis",
    target: '[data-tour="kpis"]',
    title: "Your dashboard, built for you",
    body: "KPIs, trends, forecasts, anomalies and breakdowns — all computed on load. Click any KPI to make it the measure the rest of the page follows.",
  },
  {
    id: "views",
    target: '[data-tour="views"]',
    title: "Arrange it, then save it",
    body: "Hit Arrange to drag sections into the order you want, hide what you don't need, then save it as a named view. Set one as the default and it opens that way every time.",
  },
  {
    id: "ask",
    target: '[data-tour="ask"]',
    title: "Ask in plain English",
    body: "Ask “which region grew fastest last quarter?” and get an answer computed by SQL — with the query on show, so you can verify it. If the data can't answer, it says so instead of guessing.",
  },
  {
    id: "done",
    title: "That's the tour",
    body: "Everything here is traceable back to your data. You can replay this tour any time from the ? button in the header.",
  },
];
