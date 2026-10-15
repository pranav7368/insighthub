import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({
  getPublicDashboard: vi.fn(),
  getPublicInspect: vi.fn(),
  getPublicBreakdown: vi.fn(),
  getPublicVariance: vi.fn(),
  getInspect: vi.fn(),
  errorText: (err, fallback = "Something went wrong") => err?.response?.data?.detail || fallback,
}));

import * as api from "../api";
import PublicDashboard from "./PublicDashboard";

const DASH = {
  dataset: { dataset_id: "ds_1", name: "Sales" },
  row_count_filtered: 6,
  chosen_measure: "revenue",
  kpis: [{ column: "revenue", total: 15500, subtype: null, delta_pct: -2, sparkline: [1, 2] }],
  breakdowns: {}, distributions: {}, insights: [], forecasts: {}, anomalies: {},
  data_profile: { rows: 6 },
};

const INSPECT = {
  dataset: { dataset_id: "ds_1", name: "Sales" }, measure: "revenue", agg: "sum", subtype: null,
  value: 5500, row_count: 3,
  context: { filters: { region: "North" }, date_from: null, date_to: null, grain: "month", date_column: "date" },
  explanation: "Sum of revenue across 3 rows where region = North.", sql: "SELECT …",
  stats: null, contributors: [],
  trend: { grain: "month", points: [{ period: "2025-03", value: 500, rows: 1, from: "2025-03", to: "2025-03" }],
    comparison: null, latest_period_partial: false, data_through: "2025-03-10" },
  dimensions: [], measures: [{ name: "revenue" }], additive: true, notes: [],
};

beforeEach(() => {
  api.getPublicInspect.mockResolvedValue(INSPECT);
});

const open = async (meta = {}) => {
  api.getPublicDashboard.mockResolvedValue({ dashboard: DASH, meta: { hidden_sections: [], section_order: [], ...meta } });
  render(<PublicDashboard token="tok_123" />);
  await userEvent.click(await screen.findByRole("button", { name: /Revenue/ }));
  return screen.findByRole("dialog");
};

describe("drill-down on a share link", () => {
  it("opens the details panel through the token-scoped API", async () => {
    const panel = await open();
    expect(await within(panel).findByText("5,500")).toBeInTheDocument();
    expect(api.getPublicInspect).toHaveBeenCalledWith("tok_123", expect.objectContaining({ measure: "revenue" }));
    expect(api.getInspect).not.toHaveBeenCalled();     // never the signed-in API
  });

  it("offers no rows, no ask and no 'show on dashboard'", async () => {
    const panel = await open();
    await within(panel).findByText("5,500");
    const tabs = within(panel).getAllByRole("tab").map((t) => t.textContent);
    expect(tabs).toEqual(["Overview", "Why it changed", "Breakdown", "How it's calculated"]);
    expect(within(panel).queryByRole("button", { name: /see the rows/i })).toBeNull();
    expect(within(panel).queryByRole("button", { name: /show this on the dashboard/i })).toBeNull();
  });

  it("hides change analysis on a date-limited link", async () => {
    const panel = await open({ date_limited: true });
    await within(panel).findByText("5,500");
    const tabs = within(panel).getAllByRole("tab").map((t) => t.textContent);
    expect(tabs).not.toContain("Why it changed");
  });
});
