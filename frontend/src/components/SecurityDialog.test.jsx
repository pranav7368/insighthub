import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({
  getMfaStatus: vi.fn(),
  startMfaSetup: vi.fn(),
  enableMfa: vi.fn(),
  disableMfa: vi.fn(),
  revokeSessions: vi.fn(),
  downloadMyData: vi.fn(),
  errorText: (err, fallback = "Something went wrong") =>
    err?.response?.data?.detail || fallback,
}));

import * as api from "../api";
import SecurityDialog from "./SecurityDialog";

const RECOVERY = ["aaaa-bbbb-cccc", "dddd-eeee-ffff"];

beforeEach(() => {
  api.getMfaStatus.mockResolvedValue({ enabled: false, recovery_codes_remaining: 0 });
  api.startMfaSetup.mockResolvedValue({
    secret: "JBSWY3DPEHPK3PXP",
    otpauth_uri: "otpauth://totp/InsightHub:a@b.com?secret=JBSWY3DPEHPK3PXP",
  });
  api.enableMfa.mockResolvedValue({ enabled: true, recovery_codes: RECOVERY });
  api.disableMfa.mockResolvedValue({ enabled: false });
  api.revokeSessions.mockResolvedValue({ ok: true });
});

const open = (props = {}) =>
  render(<SecurityDialog onClose={vi.fn()} onSignedOut={vi.fn()} {...props} />);

describe("SecurityDialog — two-factor enrolment", () => {
  it("offers to turn it on when it is off", async () => {
    open();
    expect(await screen.findByRole("button", { name: /turn on two-factor/i })).toBeInTheDocument();
  });

  it("shows the setup key so it can be entered by hand", async () => {
    open();
    await userEvent.click(await screen.findByRole("button", { name: /turn on two-factor/i }));
    expect(await screen.findByText("JBSWY3DPEHPK3PXP")).toBeInTheDocument();
  });

  it("shows recovery codes once the code is confirmed", async () => {
    open();
    await userEvent.click(await screen.findByRole("button", { name: /turn on two-factor/i }));
    await userEvent.type(await screen.findByLabelText("6-digit code"), "123456");
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(api.enableMfa).toHaveBeenCalledWith("123456"));
    for (const code of RECOVERY) {
      expect(await screen.findByText(code)).toBeInTheDocument();
    }
  });

  it("says the recovery codes will not be shown again", async () => {
    // they are stored hashed, so this is literally true — the copy has to say
    // so or people close the dialog and lose their way back in
    open();
    await userEvent.click(await screen.findByRole("button", { name: /turn on two-factor/i }));
    await userEvent.type(await screen.findByLabelText("6-digit code"), "123456");
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(await screen.findByText(/only time they can be shown/i)).toBeInTheDocument();
  });

  it("surfaces a rejected code instead of failing silently", async () => {
    api.enableMfa.mockRejectedValue({
      response: { data: { detail: "that code is not valid — check the time on your device" } },
    });
    open();
    await userEvent.click(await screen.findByRole("button", { name: /turn on two-factor/i }));
    await userEvent.type(await screen.findByLabelText("6-digit code"), "000000");
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(await screen.findByText(/not valid/i)).toBeInTheDocument();
  });

  it("does not leave the setup screen when the code is rejected", async () => {
    api.enableMfa.mockRejectedValue({ response: { data: { detail: "nope" } } });
    open();
    await userEvent.click(await screen.findByRole("button", { name: /turn on two-factor/i }));
    await userEvent.type(await screen.findByLabelText("6-digit code"), "000000");
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(await screen.findByLabelText("6-digit code")).toBeInTheDocument();
  });
});

describe("SecurityDialog — turning it off", () => {
  beforeEach(() => {
    api.getMfaStatus.mockResolvedValue({ enabled: true, recovery_codes_remaining: 7 });
  });

  it("reports the remaining recovery codes", async () => {
    open();
    expect(await screen.findByText(/7 recovery codes left/i)).toBeInTheDocument();
  });

  it("requires the password", async () => {
    open();
    await userEvent.type(await screen.findByPlaceholderText(/confirm your password/i), "hunter22");
    await userEvent.click(screen.getByRole("button", { name: /turn off/i }));
    await waitFor(() => expect(api.disableMfa).toHaveBeenCalledWith("hunter22"));
  });

  it("shows why a wrong password was refused", async () => {
    api.disableMfa.mockRejectedValue({ response: { data: { detail: "password is incorrect" } } });
    open();
    await userEvent.type(await screen.findByPlaceholderText(/confirm your password/i), "wrong");
    await userEvent.click(screen.getByRole("button", { name: /turn off/i }));

    expect(await screen.findByText(/password is incorrect/i)).toBeInTheDocument();
  });
});

describe("SecurityDialog — sessions and personal data", () => {
  it("signs the current session out too, since that is the point", async () => {
    const onSignedOut = vi.fn();
    open({ onSignedOut });

    await userEvent.click(await screen.findByRole("button", { name: /sign out everywhere/i }));
    await waitFor(() => expect(onSignedOut).toHaveBeenCalledOnce());
  });

  it("downloads the personal data export", async () => {
    open();
    await userEvent.click(await screen.findByRole("button", { name: /download my data/i }));
    await waitFor(() => expect(api.downloadMyData).toHaveBeenCalledOnce());
  });

  it("reports a failure to load rather than showing a blank panel", async () => {
    api.getMfaStatus.mockRejectedValue({ response: { data: { detail: "server exploded" } } });
    open();
    expect(await screen.findByText(/server exploded/i)).toBeInTheDocument();
  });
});
