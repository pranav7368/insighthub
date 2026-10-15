import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({
  listAlerts: vi.fn(),
  getSchema: vi.fn(),
  createAlert: vi.fn(),
  deleteAlert: vi.fn(),
  setAlertEnabled: vi.fn(),
  testAlert: vi.fn(),
  setTarget: vi.fn(),
  deleteTarget: vi.fn(),
  errorText: (err, fallback = "Something went wrong") => err?.response?.data?.detail || fallback,
}));

import * as api from "../api";
import { makeCtx } from "../drill";
import AlertsDialog from "./AlertsDialog";
import TargetPanel from "./TargetPanel";

const TARGET = {
  target_id: "tgt_1", measure: "revenue", grain: "month", period: "2025-11", value: 1100, filters: {},
  actual: 1000, projection: 1071, progress: 0.91, projected_ratio: 0.97, days: 30, days_elapsed: 28,
  days_remaining: 2, needed_per_day: 50, current: true, status: "at_risk",
};

beforeEach(() => {
  api.listAlerts.mockResolvedValue([]);
  api.getSchema.mockResolvedValue([{ name: "revenue", role: "measure" }, { name: "units", role: "measure" }]);
  api.createAlert.mockResolvedValue({});
});

describe("target → alert", () => {
  it("offers an alert on a current whole-dataset target, pre-filled", async () => {
    const onRequestAlert = vi.fn();
    render(<TargetPanel datasetId="ds" ctx={makeCtx({ measure: "revenue" })} target={TARGET} subtype={null}
      lastDate="2025-11-28" canEdit onChanged={vi.fn()} onRequestAlert={onRequestAlert} />);
    await userEvent.click(screen.getByRole("button", { name: /alert me if this falls behind/i }));
    expect(onRequestAlert).toHaveBeenCalledWith({
      aggregate: "target_pace", measure: "revenue", op: "lt", threshold: 90, name: "Revenue falling behind target",
    });
  });

  it("does not offer it for a segment target (pace alerts watch the whole dataset)", () => {
    render(<TargetPanel datasetId="ds" ctx={makeCtx({ measure: "revenue", filters: { region: "N" } })}
      target={{ ...TARGET, filters: { region: "N" } }} lastDate="2025-11-28" canEdit onChanged={vi.fn()}
      onRequestAlert={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /alert me/i })).toBeNull();
  });

  it("the alerts dialog opens filled in and explains pace", async () => {
    render(<AlertsDialog datasetId="ds" onClose={vi.fn()}
      preset={{ aggregate: "target_pace", measure: "revenue", op: "lt", threshold: 90, name: "Revenue falling behind target" }} />);
    expect(await screen.findByDisplayValue("Revenue falling behind target")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Pace vs current target %")).toBeInTheDocument();
    expect(screen.getByDisplayValue("90")).toBeInTheDocument();
    expect(screen.getByText(/100% means on course to hit it/)).toBeInTheDocument();
    await userEvent.type(screen.getByPlaceholderText(/hooks.slack.com/), "https://hooks.example.com/x");
    await userEvent.click(screen.getByRole("button", { name: "Create alert" }));
    expect(api.createAlert).toHaveBeenCalledWith("ds", expect.objectContaining({
      aggregate: "target_pace", measure: "revenue", op: "lt", threshold: 90,
    }));
  });
});
