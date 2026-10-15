import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({
  getActions: vi.fn(),
  setTarget: vi.fn(),
  deleteTarget: vi.fn(),
  queryData: vi.fn(),
  getMetricExplain: vi.fn(),
  errorText: (err, fallback = "Something went wrong") => err?.response?.data?.detail || fallback,
}));

import * as api from "../api";
import { currentPeriod, makeCtx, targetFor } from "../drill";
import ActionsPanel from "./ActionsPanel";
import AskInContext from "./AskInContext";
import CertifiedMetrics from "./CertifiedMetrics";
import { Significance } from "./ChangeAnalysis";
import KpiCard from "./KpiCard";
import TargetPanel from "./TargetPanel";

const TARGET = {
  target_id: "tgt_1", measure: "revenue", grain: "month", period: "2025-11", value: 1100, filters: {},
  from: "2025-11-01", to: "2025-11-30", actual: 1000, projection: 1071.4, progress: 0.909, projected_ratio: 0.974,
  gap: -28.6, days: 30, days_elapsed: 28, days_remaining: 2, needed_per_day: 50, current: true, status: "at_risk",
};

beforeEach(() => {
  api.getActions.mockResolvedValue({
    actions: [
      { id: "unusual_move:revenue", kind: "unusual_move", severity: "high", title: "Investigate the drop in revenue",
        why: "Revenue fell 613 from Oct 2025 to Nov 2025 — 4.1× its typical month-to-month swing of 18.",
        action: "Open the change breakdown.", evidence: { measure: "revenue", filters: {}, tab: "change" } },
      { id: "growing_segment:region=South", kind: "growing_segment", severity: "low", title: "Build on South's growth",
        why: "South: 400 → 500 (+25%).", action: "Find what is working.", evidence: { measure: "revenue", filters: { region: "South" } } },
    ],
  });
  api.setTarget.mockResolvedValue(TARGET);
  api.queryData.mockResolvedValue({
    kind: "scalar", value: 400, subtype: null, answer: "Total revenue is 400.", query: "sum of revenue where region = North",
    sql: "SELECT SUM(\"revenue\") AS v FROM \"sales\" WHERE \"region\" = 'North'",
  });
  api.getMetricExplain.mockResolvedValue({
    kind: "ratio", a: { label: "Oct 2025", value: 19.8 }, b: { label: "Nov 2025", value: 16 }, delta: -3.8,
    numerator: { agg: "sum", column: "profit", a: 320, b: 160, effect: -9.9, drill: { measure: "profit", agg: "sum" } },
    denominator: { agg: "sum", column: "revenue", a: 1613, b: 1000, effect: 6.1, drill: { measure: "revenue", agg: "sum" } },
    summary: "Margin moved mostly because profit fell (numerator of the ratio).", like_for_like: true,
  });
});

describe("helpers", () => {
  it("finds the target for a slice", () => {
    expect(targetFor([TARGET], { measure: "revenue", filters: {} })).toBe(TARGET);
    expect(targetFor([TARGET], { measure: "revenue", filters: { region: "N" } })).toBeNull();
    expect(targetFor([TARGET], { measure: "revenue", filters: {}, date_from: "2025-11", date_to: "2025-11" })).toBe(TARGET);
    expect(targetFor([TARGET], { measure: "revenue", filters: {}, date_from: "2025-10", date_to: "2025-10" })).toBeNull();
  });
  it("names the current period", () => {
    expect(currentPeriod("2026-10-28", "month")).toBe("2026-10");
    expect(currentPeriod("2026-10-28", "quarter")).toBe("2026-Q4");
    expect(currentPeriod("2026-10-28", "year")).toBe("2026");
  });
});

describe("ActionsPanel", () => {
  it("lists actions most-severe first and opens their evidence", async () => {
    const onOpen = vi.fn();
    render(<ActionsPanel datasetId="ds" measure="revenue" filters={{}} onOpen={onOpen} />);
    expect(await screen.findByText("Investigate the drop in revenue")).toBeInTheDocument();
    expect(screen.getByText("Act now")).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: /see the evidence/i })[1]);
    expect(onOpen).toHaveBeenCalledWith({ measure: "revenue", filters: { region: "South" } });
  });

  it("renders nothing when there is nothing to recommend", async () => {
    api.getActions.mockResolvedValue({ actions: [] });
    const { container } = render(<ActionsPanel datasetId="ds" measure="revenue" filters={{}} onOpen={vi.fn()} />);
    // wait for the request to settle, then check nothing was rendered for it
    await waitFor(() => expect(api.getActions).toHaveBeenCalled());
    await api.getActions.mock.results[0].value;
    expect(container).toBeEmptyDOMElement();
  });
});

describe("TargetPanel", () => {
  const ctx = makeCtx({ measure: "revenue", filters: { region: "North" } });

  it("shows the pace and what it takes to close the gap", () => {
    render(<TargetPanel datasetId="ds" ctx={ctx} target={TARGET} subtype={null} lastDate="2025-11-28" onChanged={vi.fn()} />);
    expect(screen.getByText("At risk")).toBeInTheDocument();
    expect(screen.getByText(/at this pace/)).toBeInTheDocument();
    expect(screen.getByText(/remaining 2 days need 50 a day/)).toBeInTheDocument();
  });

  it("lets an editor set a target for exactly this segment", async () => {
    const onChanged = vi.fn();
    render(<TargetPanel datasetId="ds" ctx={ctx} target={null} subtype={null} lastDate="2025-11-28" canEdit onChanged={onChanged} />);
    await userEvent.click(screen.getByRole("button", { name: "Set a target" }));
    expect(screen.getByDisplayValue("2025-11")).toBeInTheDocument();
    await userEvent.type(screen.getByRole("spinbutton"), "1500");
    await userEvent.click(screen.getByRole("button", { name: "Save target" }));
    expect(api.setTarget).toHaveBeenCalledWith("ds", {
      measure: "revenue", grain: "month", period: "2025-11", value: 1500, filters: { region: "North" },
    });
    expect(onChanged).toHaveBeenCalled();
  });

  it("is hidden from viewers when no target exists", () => {
    const { container } = render(<TargetPanel datasetId="ds" ctx={ctx} target={null} lastDate="2025-11-28" onChanged={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("AskInContext", () => {
  it("asks inside the drilled slice and shows how it was computed", async () => {
    const ctx = makeCtx({ measure: "revenue", filters: { region: "North" }, date_from: "2025-11", date_to: "2025-11" });
    render(<AskInContext datasetId="ds" ctx={ctx} />);
    expect(screen.getByText(/Region: North · 2025-11 → 2025-11/)).toBeInTheDocument();
    await userEvent.type(screen.getByRole("textbox", { name: /question/i }), "total revenue");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(api.queryData).toHaveBeenCalledWith("ds", "total revenue",
      { filters: { region: "North" }, date_from: "2025-11", date_to: "2025-11" });
    expect(await screen.findByText("Total revenue is 400.")).toBeInTheDocument();
    expect(screen.getByText(/How this was computed/)).toBeInTheDocument();
  });

  it("shows a refusal instead of a made-up answer", async () => {
    api.queryData.mockRejectedValue({ response: { data: { detail: "no rows match region = North" } } });
    render(<AskInContext datasetId="ds" ctx={makeCtx({ measure: "revenue" })} />);
    await userEvent.click(screen.getByRole("button", { name: "revenue by month" }));
    expect(await screen.findByText("no rows match region = North")).toBeInTheDocument();
  });
});

describe("significance, KPI targets and the metric tree", () => {
  it("says when a move is unusual and on what basis", () => {
    render(<Significance sig={{ level: "unusual", z: -4.1, typical_change: 18, history: 9, window_days: 28 }} grain="month" subtype={null} />);
    expect(screen.getByText("Unusual")).toBeInTheDocument();
    expect(screen.getByText(/4.1× the typical month-to-month swing of ±18/)).toBeInTheDocument();
    expect(screen.getByText(/9 earlier changes, each over the first 28 days/)).toBeInTheDocument();
  });

  it("puts the target on the KPI card", () => {
    const kpi = { column: "revenue", total: 15000, subtype: null, delta_pct: -2, sparkline: [1, 2] };
    render(<KpiCard kpi={kpi} onSelect={vi.fn()} target={TARGET} />);
    expect(screen.getByText(/At risk · pace 97% of 1,100/)).toBeInTheDocument();
  });

  it("splits a ratio metric into its parts and drills into one", async () => {
    const onInspect = vi.fn();
    render(<CertifiedMetrics onInspect={onInspect}
      metrics={[{ metric_id: "m1", name: "Margin", value: 16, format: "percent", sql: "SELECT …" }]} />);
    await userEvent.click(screen.getByRole("button", { name: "What moved it?" }));
    expect(await screen.findByText(/profit fell/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /numerator/ }));
    expect(onInspect).toHaveBeenCalledWith({ measure: "profit", agg: "sum", tab: "change", compare: "previous" });
  });
});
