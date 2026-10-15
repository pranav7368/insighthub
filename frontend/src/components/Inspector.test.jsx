import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({
  getInspect: vi.fn(),
  getBreakdown: vi.fn(),
  getRows: vi.fn(),
  exportRowsCsv: vi.fn(),
  errorText: (err, fallback = "Something went wrong") => err?.response?.data?.detail || fallback,
}));

import * as api from "../api";
import { makeCtx } from "../drill";
import Inspector from "./Inspector";

const INSPECT = {
  dataset: { dataset_id: "ds_1", name: "Sales" },
  measure: "revenue", agg: "sum", subtype: "currency", value: 800, row_count: 6,
  context: { filters: { region: "North" }, date_from: null, date_to: null, grain: "month", date_column: "date" },
  explanation: "Sum of revenue across 6 rows where region = North.",
  sql: 'SELECT SUM("revenue") AS value FROM "Sales" WHERE "region" = \'North\'',
  stats: { rows_with_value: 6, min: 50, median: 100, avg: 133, max: 300, std: 90 },
  trend: {
    grain: "month", truncated: false, latest_period_partial: false, data_through: "2025-03-31",
    points: [
      { period: "2025-02", value: 300, rows: 2, from: "2025-02", to: "2025-02" },
      { period: "2025-03", value: 450, rows: 3, from: "2025-03", to: "2025-03" },
    ],
    comparison: {
      period: "2025-03", value: 450,
      previous: { period: "2025-02", value: 300, delta: 150, pct: 50 },
      year_ago: null,
    },
  },
  contributors: [{
    dimension: "product", subtype: null, distinct: 3,
    items: [{ name: "Gadget", value: 300, rows: 1, share_pct: 66.7 }],
    others: { count: 2, value: 150, rows: 2, share_pct: 33.3 },
  }],
  dimensions: [{ name: "region", pinned: true }, { name: "product", pinned: false }],
  measures: [{ name: "revenue", subtype: "currency" }],
  additive: true,
  notes: ["Your row-access rules apply: this number covers only the rows you are allowed to see."],
};

beforeEach(() => {
  api.getInspect.mockResolvedValue(INSPECT);
  api.getBreakdown.mockResolvedValue({
    dimension: "product", distinct: 3, subtype: "currency", others: null,
    items: [{ name: "Gadget", value: 300, rows: 1, share_pct: 66.7 }, { name: "Widget", value: 150, rows: 2, share_pct: 33.3 }],
  });
  api.getRows.mockResolvedValue({
    columns: [{ name: "region", role: "dimension" }, { name: "revenue", role: "measure", subtype: "currency" }],
    rows: [["North", 300], ["North", 100]], total: 2, page: 1, page_size: 50, sort: "revenue", desc: true,
  });
});

const ctx = makeCtx({ measure: "revenue", filters: { region: "North" } });
const open = (over = {}) => {
  const props = { datasetId: "ds_1", ctx, onNavigate: vi.fn(), onClose: vi.fn(), onApply: vi.fn(), ...over };
  render(<Inspector {...props} />);
  return props;
};

describe("Inspector", () => {
  it("shows the number, its comparison, notes and the drill path", async () => {
    open();
    expect(await screen.findByText("₹800")).toBeInTheDocument();
    expect(screen.getByText(/across 6 rows of Sales/)).toBeInTheDocument();
    expect(screen.getByText(/▲ 50.0%/)).toBeInTheDocument();
    expect(screen.getByText(/row-access rules apply/)).toBeInTheDocument();
    const path = screen.getByRole("navigation", { name: /drill path/i });
    expect(within(path).getByText("Region: North")).toHaveAttribute("aria-current", "page");
  });

  it("clicking a contributor drills one level deeper", async () => {
    const props = open();
    await userEvent.click(await screen.findByRole("button", { name: /Gadget/ }));
    expect(props.onNavigate).toHaveBeenCalledWith(
      expect.objectContaining({ filters: { region: "North", product: "Gadget" } }), { replace: false });
  });

  it("the 'other' bucket opens the full breakdown", async () => {
    const props = open();
    await userEvent.click(await screen.findByRole("button", { name: /Other \(2 more\)/ }));
    expect(props.onNavigate).toHaveBeenCalledWith(
      expect.objectContaining({ tab: "breakdown", dimension: "product" }), { replace: false });
  });

  it("a crumb walks back up the path", async () => {
    const props = open();
    await userEvent.click(await screen.findByRole("button", { name: "Revenue" }));
    expect(props.onNavigate).toHaveBeenCalledWith(expect.objectContaining({ filters: {} }), { replace: false });
  });

  it("shows the plain-words formula and the exact SQL", async () => {
    open({ ctx: { ...ctx, tab: "proof" } });
    expect(await screen.findByText(INSPECT.explanation)).toBeInTheDocument();
    expect(screen.getByText(INSPECT.sql)).toBeInTheDocument();
  });

  it("lists the rows behind the number", async () => {
    open({ ctx: { ...ctx, tab: "records" } });
    expect(await screen.findByText("1–2 of 2 rows")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /Revenue/ })).toHaveAttribute("aria-sort", "descending");
    expect(screen.getAllByRole("row")).toHaveLength(3);
  });

  it("the breakdown tab ranks every value", async () => {
    open({ ctx: { ...ctx, tab: "breakdown", dimension: "product" } });
    expect(await screen.findByRole("button", { name: /Widget/ })).toBeInTheDocument();
    expect(api.getBreakdown).toHaveBeenCalledWith("ds_1", expect.anything(), "product", 50);
  });

  it("Escape closes it, and 'show on dashboard' hands back the slice", async () => {
    const props = open();
    await screen.findByText("₹800");
    await userEvent.keyboard("{Escape}");
    expect(props.onClose).toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: /show this on the dashboard/i }));
    expect(props.onApply).toHaveBeenCalledWith(ctx);
  });

  it("an API error is shown, not thrown", async () => {
    api.getInspect.mockRejectedValue({ response: { data: { detail: "unknown column 'x'" } } });
    open();
    expect(await screen.findByText("unknown column 'x'")).toBeInTheDocument();
  });

  it("has no structural accessibility violations", async () => {
    const { container } = render(<Inspector datasetId="ds_1" ctx={ctx} onNavigate={vi.fn()} onClose={vi.fn()} onApply={vi.fn()} />);
    await screen.findByText("₹800");
    await waitFor(async () => {
      const r = await axe.run(container, {
        resultTypes: ["violations"],
        runOnly: { type: "rule", values: ["button-name", "label", "select-name", "aria-valid-attr-value", "aria-required-children", "list", "listitem", "definition-list", "dlitem"] },
      });
      expect(r.violations.map((v) => v.id)).toEqual([]);
    });
  });
});
