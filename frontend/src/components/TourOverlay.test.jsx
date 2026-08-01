import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import TourOverlay from "./TourOverlay";

const STEPS = [
  { id: "welcome", title: "Welcome", body: "no anchor, always shows" },
  { id: "upload", target: '[data-tour="upload"]', title: "Bring your data", body: "upload" },
  { id: "kpis", target: '[data-tour="kpis"]', title: "Your dashboard", body: "kpis" },
  { id: "done", title: "That's the tour", body: "finished" },
];

/** Put a subset of the anchors on the page, as a real screen would. */
function withAnchors(...names) {
  const host = document.createElement("div");
  for (const name of names) {
    const el = document.createElement("div");
    el.setAttribute("data-tour", name);
    host.appendChild(el);
  }
  document.body.appendChild(host);
  return host;
}

describe("TourOverlay", () => {
  it("skips steps whose anchor is not on the page", async () => {
    // the whole point: one script covers an empty workspace and a populated
    // one, without a second "empty state" tour to keep in sync
    withAnchors("upload");
    render(<TourOverlay steps={STEPS} onFinish={vi.fn()} />);

    expect(screen.getByText("Welcome")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("Bring your data")).toBeInTheDocument();

    // 'kpis' has no anchor here, so Next must land on the final step
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("That's the tour")).toBeInTheDocument();
  });

  it("shows every step when all anchors exist", async () => {
    withAnchors("upload", "kpis");
    render(<TourOverlay steps={STEPS} onFinish={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("Your dashboard")).toBeInTheDocument();
  });

  it("calls onFinish from the last step", async () => {
    const onFinish = vi.fn();
    render(<TourOverlay steps={[STEPS[0]]} onFinish={onFinish} />);

    await userEvent.click(screen.getByRole("button", { name: "Get started" }));
    expect(onFinish).toHaveBeenCalledOnce();
  });

  it("calls onFinish when skipped", async () => {
    const onFinish = vi.fn();
    render(<TourOverlay steps={STEPS} onFinish={onFinish} />);

    await userEvent.click(screen.getByRole("button", { name: "Skip tour" }));
    expect(onFinish).toHaveBeenCalledOnce();
  });

  it("has no Back button on the first step", () => {
    render(<TourOverlay steps={STEPS} onFinish={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Back" })).not.toBeInTheDocument();
  });

  it("goes back", async () => {
    render(<TourOverlay steps={[STEPS[0], STEPS[3]]} onFinish={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("That's the tour")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByText("Welcome")).toBeInTheDocument();
  });

  it("closes on Escape", async () => {
    const onFinish = vi.fn();
    render(<TourOverlay steps={STEPS} onFinish={onFinish} />);

    await userEvent.keyboard("{Escape}");
    expect(onFinish).toHaveBeenCalledOnce();
  });

  it("advances on ArrowRight and retreats on ArrowLeft", async () => {
    render(<TourOverlay steps={[STEPS[0], STEPS[3]]} onFinish={vi.fn()} />);

    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByText("That's the tour")).toBeInTheDocument();
    await userEvent.keyboard("{ArrowLeft}");
    expect(screen.getByText("Welcome")).toBeInTheDocument();
  });

  it("renders nothing when no step can be shown", () => {
    const { container } = render(
      <TourOverlay steps={[{ id: "x", target: '[data-tour="absent"]', title: "X", body: "x" }]}
        onFinish={vi.fn()} />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("blocks interaction with the app underneath", () => {
    render(<TourOverlay steps={STEPS} onFinish={vi.fn()} />);
    expect(document.querySelector(".tour__blocker")).toBeInTheDocument();
  });
});
