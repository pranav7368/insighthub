import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal()),
  getDashboard: vi.fn(),
  getActions: vi.fn(),
  getExplain: vi.fn(),
  getTargets: vi.fn(),
  listMetrics: vi.fn(),
  listViews: vi.fn(),
  createView: vi.fn(),
}));

import * as api from "../api";
import DashboardView from "./DashboardView";

const dashboard = (rows) => ({
  dataset: { dataset_id: "ds", name: "Sales" }, row_count_filtered: rows,
  kpis: [], breakdowns: {}, distributions: {}, filter_options: { region: ["North", "South"] },
  data_profile: { rows, date_span: { from: "2026-01-01", to: "2026-10-28" } },
  chosen_measure: null, insights: [],
});

beforeEach(() => {
  api.getActions.mockResolvedValue({ actions: [] });
  api.getExplain.mockResolvedValue(null);
  api.getTargets.mockResolvedValue([]);
  api.listMetrics.mockResolvedValue([]);
  api.listViews.mockResolvedValue([]);
  window.history.replaceState(null, "", "/");
});

describe("DashboardView", () => {
  it("says so when the filters leave no rows, and clears them in one click", async () => {
    window.history.replaceState(null, "", `/?ds=ds&f=${encodeURIComponent(JSON.stringify({ region: "Nowhere" }))}`);
    api.getDashboard.mockImplementation(async (_id, params) => dashboard(params.region ? 0 : 120));
    render(<DashboardView datasetId="ds" />);
    expect(await screen.findByRole("heading", { name: "No rows match this view" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Clear filters and dates" }));
    await waitFor(() => expect(screen.queryByText("No rows match this view")).toBeNull());
    expect(api.getDashboard).toHaveBeenLastCalledWith("ds", {});
  });

  it("does not show the empty state for an unfiltered empty dataset", async () => {
    api.getDashboard.mockResolvedValue(dashboard(0));
    render(<DashboardView datasetId="ds" />);
    expect(await screen.findByRole("heading", { name: "Sales" })).toBeInTheDocument();
    expect(screen.queryByText("No rows match this view")).toBeNull();
  });

  it("reports a failed view save as a toast and keeps the page", async () => {
    api.getDashboard.mockResolvedValue(dashboard(120));
    api.createView.mockRejectedValue({ response: { data: { detail: "A view with that name exists." } } });
    const toast = await import("../toast");
    const seen = [];
    const off = toast.subscribe((t) => seen.push(t));
    render(<DashboardView datasetId="ds" canEdit />);
    await screen.findByRole("heading", { name: "Sales" });
    await userEvent.click(screen.getByRole("button", { name: "Save view" }));
    await userEvent.type(screen.getByRole("textbox"), "Q3{Enter}");
    await waitFor(() => expect(seen.map((t) => t.message)).toContain("A view with that name exists."));
    expect(seen.at(-1).kind).toBe("error");
    // the dashboard is still there: a failed save is not a page error
    expect(screen.getByRole("heading", { name: "Sales" })).toBeInTheDocument();
    off();
  });
});
