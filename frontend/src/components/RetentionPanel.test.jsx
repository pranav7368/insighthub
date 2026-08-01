import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({
  getRetention: vi.fn(),
  previewRetention: vi.fn(),
  setRetention: vi.fn(),
  runRetention: vi.fn(),
  errorText: (err, fallback = "Something went wrong") =>
    err?.response?.data?.detail || fallback,
}));

import * as api from "../api";
import RetentionPanel from "./RetentionPanel";

const OFF = {
  audit_days: 0, archive_days: 0, dataset_days: 0,
  minimum_days: 7, minimum_dataset_days: 30,
};

beforeEach(() => {
  api.getRetention.mockResolvedValue(OFF);
  api.previewRetention.mockResolvedValue({
    audit_entries: 12, archived_rows: 3,
    datasets: [{ dataset_id: "ds1", name: "Old Sales" }],
  });
  api.setRetention.mockResolvedValue({ ...OFF, audit_days: 30 });
  api.runRetention.mockResolvedValue({ audit_entries: 12, archived_rows: 3, datasets: [] });
});

const field = (label) => screen.getByLabelText(label);

describe("RetentionPanel", () => {
  it("reads as keep-forever until something is set", async () => {
    render(<RetentionPanel />);
    await waitFor(() => expect(api.getRetention).toHaveBeenCalled());

    expect(field("Activity log")).toHaveValue(0);
    expect(screen.getAllByText("keep forever")).toHaveLength(3);
  });

  it("says plainly that this is workspace-wide", async () => {
    // it sits inside a dialog titled after one dataset, so the scope has to be
    // stated rather than discovered
    render(<RetentionPanel />);
    expect(await screen.findByText(/whole workspace/i)).toBeInTheDocument();
  });

  it("cannot preview while everything is off", async () => {
    render(<RetentionPanel />);
    await waitFor(() => expect(api.getRetention).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: /preview what this deletes/i })).toBeDisabled();
  });

  it("shows what a policy would delete", async () => {
    render(<RetentionPanel />);
    await waitFor(() => expect(api.getRetention).toHaveBeenCalled());

    await userEvent.clear(field("Activity log"));
    await userEvent.type(field("Activity log"), "30");
    await userEvent.click(screen.getByRole("button", { name: /preview what this deletes/i }));

    expect(await screen.findByText(/12 activity log entries/i)).toBeInTheDocument();
    expect(screen.getByText(/Old Sales/)).toBeInTheDocument();
  });

  /** The property that matters: looking must never arm. */
  it("does not save when previewing", async () => {
    render(<RetentionPanel />);
    await waitFor(() => expect(api.getRetention).toHaveBeenCalled());

    await userEvent.clear(field("Activity log"));
    await userEvent.type(field("Activity log"), "30");
    await userEvent.click(screen.getByRole("button", { name: /preview what this deletes/i }));
    await screen.findByText(/12 activity log entries/i);

    expect(api.setRetention).not.toHaveBeenCalled();
    expect(screen.getByText(/nothing has been deleted/i)).toBeInTheDocument();
  });

  it("discards a stale preview when the numbers change", async () => {
    render(<RetentionPanel />);
    await waitFor(() => expect(api.getRetention).toHaveBeenCalled());

    await userEvent.clear(field("Activity log"));
    await userEvent.type(field("Activity log"), "30");
    await userEvent.click(screen.getByRole("button", { name: /preview what this deletes/i }));
    await screen.findByText(/12 activity log entries/i);

    await userEvent.clear(field("Activity log"));
    await userEvent.type(field("Activity log"), "90");
    // a preview of a different policy is worse than no preview
    expect(screen.queryByText(/12 activity log entries/i)).not.toBeInTheDocument();
  });

  it("saves the policy that is on screen", async () => {
    render(<RetentionPanel />);
    await waitFor(() => expect(api.getRetention).toHaveBeenCalled());

    await userEvent.clear(field("Uploaded data"));
    await userEvent.type(field("Uploaded data"), "365");
    await userEvent.click(screen.getByRole("button", { name: /save policy/i }));

    await waitFor(() => expect(api.setRetention).toHaveBeenCalledWith(
      expect.objectContaining({ dataset_days: 365 })
    ));
  });

  it("cannot save when nothing has changed", async () => {
    render(<RetentionPanel />);
    await waitFor(() => expect(api.getRetention).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: /save policy/i })).toBeDisabled();
  });

  it("surfaces a period the server refuses", async () => {
    api.setRetention.mockRejectedValue({
      response: { data: { detail: "audit retention must be at least 7 days" } },
    });
    render(<RetentionPanel />);
    await waitFor(() => expect(api.getRetention).toHaveBeenCalled());

    await userEvent.clear(field("Activity log"));
    await userEvent.type(field("Activity log"), "1");
    await userEvent.click(screen.getByRole("button", { name: /save policy/i }));

    expect(await screen.findByText(/at least 7 days/i)).toBeInTheDocument();
  });

  it("states the minimum periods up front", async () => {
    render(<RetentionPanel />);
    expect(await screen.findByText(/Minimum 7 days, or 30 for uploaded data/i)).toBeInTheDocument();
  });

  it("only offers Run sweep once a policy is actually saved", async () => {
    api.getRetention.mockResolvedValue({ ...OFF, audit_days: 30 });
    render(<RetentionPanel />);
    expect(await screen.findByRole("button", { name: /run sweep now/i })).toBeInTheDocument();
  });

  it("reports a failure to load rather than showing empty fields", async () => {
    api.getRetention.mockRejectedValue({ response: { data: { detail: "nope" } } });
    render(<RetentionPanel />);
    expect(await screen.findByText(/nope/i)).toBeInTheDocument();
  });
});
