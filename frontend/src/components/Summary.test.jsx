import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({ getVariance: vi.fn() }));

import * as api from "../api";
import KpiCard from "./KpiCard";
import SummaryCard from "./SummaryCard";

const CHANGE = {
  delta: -254, pct: -0.7, like_for_like: true,
  a: { label: "1 Sep – 28 Sep 2026" }, b: { label: "1 Oct – 28 Oct 2026" },
  summary: "Profit fell 0.7% (−₹254) from 1 Sep – 28 Sep 2026 to 1 Oct – 28 Oct 2026.",
  significance: { level: "normal", z: -0.4 },
};
const ACTIONS = [
  { id: "a1", severity: "high", title: "Investigate the drop", evidence: { tab: "change" } },
  { id: "a2", severity: "medium", title: "Review pricing", evidence: { filters: { product: "Widget" } } },
  { id: "a3", severity: "low", title: "Build on East", evidence: {} },
];

// braces matter: a function returned from beforeEach runs as a teardown hook
beforeEach(() => { api.getVariance.mockResolvedValue(CHANGE); });

describe("SummaryCard", () => {
  const open = (over = {}) => {
    const props = { datasetId: "ds", measure: "profit", subtype: "currency", filters: {}, actions: ACTIONS,
      target: { status: "at_risk", period: "2026-10", projected_ratio: 0.93 },
      onOpen: vi.fn(), onSeeActions: vi.fn(), ...over };
    render(<SummaryCard {...props} />);
    return props;
  };

  it("leads with what happened, how unusual it is, and the target", async () => {
    open();
    expect(await screen.findByText(CHANGE.summary)).toBeInTheDocument();
    expect(screen.getByText("Normal move")).toBeInTheDocument();
    expect(screen.getByText("Like-for-like days")).toBeInTheDocument();
    expect(screen.getByText(/Target 2026-10: At risk · pace 93%/)).toBeInTheDocument();
  });

  it("shows the top two actions, each opening its evidence, and links to the rest", async () => {
    const props = open();
    await screen.findByText(CHANGE.summary);
    expect(screen.queryByText("Build on East")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Review pricing/ }));
    expect(props.onOpen).toHaveBeenCalledWith({ filters: { product: "Widget" } });
    await userEvent.click(screen.getByRole("button", { name: "All 3 recommended actions" }));
    expect(props.onSeeActions).toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: /See why it changed/ }));
    expect(props.onOpen).toHaveBeenLastCalledWith({ measure: "profit", tab: "change", compare: "previous" });
  });

  it("stays out of the way when there is nothing to say", async () => {
    api.getVariance.mockRejectedValue(new Error("no date column"));
    const { container } = render(<SummaryCard datasetId="ds" measure="profit" filters={{}} actions={[]}
      onOpen={vi.fn()} onSeeActions={vi.fn()} />);
    // no change to explain, no target, no actions: the card removes itself
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});

describe("KpiCard", () => {
  const kpi = { column: "revenue", total: 1460000, subtype: "currency", delta_pct: -2.2,
    period_label: "2026-10", current_period: 136000, sparkline: [1, 2, 3] };

  it("carries the certified mark, longer-run growth and a human date", () => {
    render(<KpiCard kpi={kpi} onSelect={vi.fn()} certified="Revenue" growth={{ mom: -2.2, qoq: 11, yoy: null }} />);
    expect(screen.getByText("✓ certified")).toHaveAttribute("title", expect.stringContaining("Revenue"));
    expect(screen.getByText(/in Oct 2026/)).toBeInTheDocument();
    expect(screen.getByText("QoQ").parentElement).toHaveTextContent("QoQ ▲11%");
    expect(screen.queryByText("YoY")).toBeNull();
    expect(screen.getByText(/vs previous month/)).toBeInTheDocument();
  });
});
