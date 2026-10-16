import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({
  listApiKeys: vi.fn(),
  createApiKey: vi.fn(),
  revokeApiKey: vi.fn(),
  errorText: (err, fallback) => err?.response?.data?.detail || fallback,
}));

import * as api from "../api";
import ApiKeysDialog from "./ApiKeysDialog";

const KEY = {
  key_id: "0123456789abcdef", name: "Power BI", role: "viewer", hint: "ihk_0123456789abcdef_…",
  created_by_email: "boss@example.com", created_at: "2026-10-16T09:00:00", last_used_at: null,
  expires_at: "2027-01-14T09:00:00", revoked_at: null,
};

beforeEach(() => {
  api.listApiKeys.mockResolvedValue([KEY]);
  api.revokeApiKey.mockResolvedValue({ ok: true });
});

describe("ApiKeysDialog", () => {
  it("lists keys by hint only, with human dates", async () => {
    render(<ApiKeysDialog onClose={vi.fn()} />);
    const row = (await screen.findByText("Power BI")).closest("tr");
    expect(within(row).getByText("ihk_0123456789abcdef_…")).toBeInTheDocument();
    expect(within(row).getByText("16 Oct 2026")).toBeInTheDocument();
    expect(within(row).getByText("Never")).toBeInTheDocument();       // last used
    expect(within(row).getByText("14 Jan 2027")).toBeInTheDocument();
  });

  it("shows a new key once, with a ready-to-run example", async () => {
    api.createApiKey.mockResolvedValue({ ...KEY, key_id: "fedcba9876543210", name: "Nightly sync",
      role: "editor", key: "ihk_fedcba9876543210_s3cret-value-xyz" });
    render(<ApiKeysDialog onClose={vi.fn()} />);
    await screen.findByText("Power BI");
    await userEvent.type(screen.getByLabelText("Name"), "Nightly sync");
    await userEvent.selectOptions(screen.getByLabelText("Access"), "editor");
    await userEvent.selectOptions(screen.getByLabelText("Expires"), "0");
    await userEvent.click(screen.getByRole("button", { name: "Create key" }));
    expect(api.createApiKey).toHaveBeenCalledWith({ name: "Nightly sync", role: "editor", expires_in_days: null });
    expect(await screen.findByLabelText("New API key")).toHaveValue("ihk_fedcba9876543210_s3cret-value-xyz");
    expect(screen.getByText(/Bearer ihk_fedcba9876543210_s3cret-value-xyz/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "I have stored it safely" }));
    expect(screen.queryByLabelText("New API key")).toBeNull();
  });

  it("asks before revoking", async () => {
    render(<ApiKeysDialog onClose={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Revoke Power BI" }));
    expect(api.revokeApiKey).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Confirm revoking Power BI" }));
    await waitFor(() => expect(api.revokeApiKey).toHaveBeenCalledWith("0123456789abcdef"));
  });

  it("has no accessibility violations", async () => {
    const { container } = render(<ApiKeysDialog onClose={vi.fn()} />);
    await screen.findByText("Power BI");
    const r = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(r.violations.map((v) => v.id)).toEqual([]);
  });
});
