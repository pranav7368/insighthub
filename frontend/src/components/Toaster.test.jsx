import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { toast, toastError } from "../toast";
import Toaster from "./Toaster";

afterEach(() => vi.useRealTimers());

describe("Toaster", () => {
  it("announces confirmations politely and errors assertively", () => {
    render(<Toaster />);
    act(() => { toast("Saved view “Q3”"); toastError("Export failed. Try again."); });
    expect(within(screen.getByRole("status")).getByText("Saved view “Q3”")).toBeInTheDocument();
    expect(within(screen.getByRole("alert")).getByText("Export failed. Try again.")).toBeInTheDocument();
  });

  it("dismisses on its own, and on request", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<Toaster />);
    act(() => { toast("Target removed"); toast("Password changed"); });
    await userEvent.click(screen.getAllByRole("button", { name: "Dismiss" })[0]);
    expect(screen.queryByText("Target removed")).toBeNull();
    act(() => { vi.advanceTimersByTime(4100); });
    expect(screen.queryByText("Password changed")).toBeNull();
  });

  it("keeps only the latest few", () => {
    render(<Toaster />);
    act(() => { ["a", "b", "c", "d"].forEach((m) => toast(m)); });
    expect(screen.queryByText("a")).toBeNull();
    expect(screen.getByText("d")).toBeInTheDocument();
  });
});
