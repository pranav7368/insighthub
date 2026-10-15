import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({
  getVariance: vi.fn(),
  getPvm: vi.fn(),
  errorText: (err, fallback = "Something went wrong") => err?.response?.data?.detail || fallback,
}));

import * as api from "../api";
import { makeCtx } from "../drill";
import ChangeAnalysis from "./ChangeAnalysis";
import DecompositionTree from "./DecompositionTree";

const VARIANCE = {
  measure: "revenue", agg: "sum", subtype: null, compare: "previous", grain: "month",
  a: { from: "2025-02-01", to: "2025-02-28", label: "Feb 2025", value: 400 },
  b: { from: "2025-03-01", to: "2025-03-31", label: "Mar 2025", value: 720 },
  delta: 320, pct: 80, like_for_like: true, data_end: "2025-03-31",
  note: "The data ends on 2025-03-31, so Mar 2025 is compared with the same number of days of Feb 2025 (like for like).",
  dimension: "region", auto_dimension: "region",
  ranking: [{ dimension: "region", score: 0.94, top: "North" }, { dimension: "product", score: 0.6, top: "Widget" }],
  steps: [
    { name: "North", blank: false, a: 100, b: 400, delta: 300, share_of_change: 0.9375 },
    { name: null, blank: true, a: 0, b: 20, delta: 20, share_of_change: 0.0625 },
  ],
  other: null, members: 2, filters: {},
  summary: "Revenue rose 80.0% (+320) from Feb 2025 to Mar 2025 — region North accounts for +300 (94% of the move).",
};

const PVM = {
  measure: "revenue", volume: "units", dimension: "product", subtype: null, volume_subtype: null,
  a: { label: "Feb 2025", value: 400, volume: 24, avg_price: 16.7 },
  b: { label: "Mar 2025", value: 720, volume: 38, avg_price: 18.9 },
  delta: 320, effects: { volume: 233.3, mix: 66.7, price: 20, unexplained: 0 },
  segments: [{ name: "Gadget", delta: 220, volume: 0, mix: 100, price: 20, qa: 4, qb: 8, price_a: 50, price_b: 52.5 }],
  candidates: ["product", "region"], volume_candidates: ["units"],
};

beforeEach(() => {
  api.getVariance.mockResolvedValue(VARIANCE);
  api.getPvm.mockResolvedValue(PVM);
});

const ctx = makeCtx({ measure: "revenue", tab: "change" });
const measures = [{ name: "revenue" }, { name: "units" }];

describe("ChangeAnalysis", () => {
  it("states the change, why, and the like-for-like caveat", async () => {
    render(<ChangeAnalysis datasetId="ds" ctx={ctx} go={vi.fn()} measures={measures} />);
    expect(await screen.findByText(VARIANCE.summary)).toBeInTheDocument();
    expect(screen.getByText(/like for like/)).toBeInTheDocument();
    expect(screen.getByText("▲ 80.0%")).toBeInTheDocument();
  });

  it("clicking a step drills into it and stays on this tab", async () => {
    const go = vi.fn();
    render(<ChangeAnalysis datasetId="ds" ctx={ctx} go={go} measures={measures} />);
    await userEvent.click(await screen.findByRole("button", { name: /North/ }));
    expect(go).toHaveBeenCalledWith(expect.objectContaining({ filters: { region: "North" }, tab: "change" }));
    // a blank member cannot be filtered on
    expect(screen.getByRole("button", { name: /\(blank\)/ })).toBeDisabled();
  });

  it("switches comparison and dimension", async () => {
    const go = vi.fn();
    render(<ChangeAnalysis datasetId="ds" ctx={ctx} go={go} measures={measures} />);
    await screen.findByText(VARIANCE.summary);
    await userEvent.click(screen.getByRole("button", { name: "a year ago" }));
    expect(go).toHaveBeenCalledWith(expect.objectContaining({ compare: "year_ago" }), true);
    await userEvent.click(screen.getByRole("button", { name: "Product" }));
    expect(go).toHaveBeenCalledWith(expect.objectContaining({ dimension: "product" }), true);
  });

  it("splits a value change into volume, mix and price", async () => {
    render(<ChangeAnalysis datasetId="ds" ctx={ctx} go={vi.fn()} measures={measures} />);
    expect(await screen.findByText("Price, volume & mix")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Gadget" })).toBeInTheDocument();
  });

  it("asks for the quantity when it cannot guess one", async () => {
    api.getPvm.mockRejectedValueOnce({ response: { data: { detail: "choose the volume measure" } } });
    render(<ChangeAnalysis datasetId="ds" ctx={ctx} go={vi.fn()} measures={measures} />);
    const pick = await screen.findByRole("combobox", { name: "Volume measure" });
    await userEvent.selectOptions(pick, "units");
    expect(api.getPvm).toHaveBeenLastCalledWith("ds", expect.anything(), { volume: "units", dimension: null });
  });

  it("explains an error instead of failing", async () => {
    api.getVariance.mockRejectedValue({ response: { data: { detail: "a change can only be broken into parts for a total or a count" } } });
    render(<ChangeAnalysis datasetId="ds" ctx={ctx} go={vi.fn()} measures={measures} />);
    expect(await screen.findByText(/only be broken into parts/)).toBeInTheDocument();
  });
});

describe("DecompositionTree", () => {
  it("splits level by level along the clicked path", async () => {
    const onInspect = vi.fn();
    render(<DecompositionTree datasetId="ds" measure="revenue" filters={{ channel: "Web" }} onInspect={onInspect} />);
    const north = await screen.findByRole("button", { name: /North/ });
    await userEvent.click(north);
    expect(north).toHaveAttribute("aria-pressed", "true");
    // the next column splits the North node, on top of the dashboard's filters
    expect(api.getVariance).toHaveBeenLastCalledWith("ds",
      expect.objectContaining({ filters: { channel: "Web", region: "North" } }), { dimension: undefined, limit: 10 });
    expect(screen.getByText("Path: Region North")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /open in details/i }));
    expect(onInspect).toHaveBeenCalledWith(expect.objectContaining({
      filters: { channel: "Web", region: "North" }, tab: "change",
    }));
  });

  it("disappears when there is no date to compare over", async () => {
    api.getVariance.mockRejectedValue({ response: { data: { detail: "no date column" } } });
    const { container } = render(<DecompositionTree datasetId="ds" measure="revenue" filters={{}} />);
    await new Promise((r) => setTimeout(r, 0));
    expect(container).toBeEmptyDOMElement();
  });
});
