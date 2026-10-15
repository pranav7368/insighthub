import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { describe, expect, it, vi } from "vitest";

import { formatDate, formatRange, formatTick } from "../format";
import Popover from "./Popover";
import Sidebar from "./Sidebar";

const DATASETS = [
  { dataset_id: "d1", name: "Retail Sales", kind: "structured", row_count: 1440 },
  { dataset_id: "d2", name: "SaaS Metrics", kind: "structured", row_count: 36 },
  { dataset_id: "doc1", name: "Policy.pdf", kind: "document", row_count: 0 },
];

const sidebar = (over = {}) => {
  const props = {
    tab: "dashboard", onTab: vi.fn(), datasets: DATASETS, datasetId: "d1", onChooseDataset: vi.fn(),
    canEdit: true, isAdmin: true, onUpload: vi.fn(), onConnect: vi.fn(), onTemplates: vi.fn(),
    onTeam: vi.fn(), onBilling: vi.fn(), onSecurity: vi.fn(), onTour: vi.fn(), onLogout: vi.fn(),
    theme: "auto", onTheme: vi.fn(), collapsed: false, onToggleCollapsed: vi.fn(),
    mobileOpen: false, onCloseMobile: vi.fn(), uploading: false, ...over,
  };
  const utils = render(<Sidebar {...props} />);
  return { props, ...utils };
};

describe("Popover", () => {
  const menu = () => render(
    <Popover menu label="More">
      {() => (<>
        <button role="menuitem">First</button>
        <button role="menuitem">Second</button>
      </>)}
    </Popover>,
  );

  it("opens a menu with focus on the first item, moves with arrows and wraps", async () => {
    menu();
    await userEvent.click(screen.getByRole("button", { name: "More" }));
    expect(screen.getByRole("menuitem", { name: "First" })).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitem", { name: "Second" })).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitem", { name: "First" })).toHaveFocus();
  });

  it("Escape closes and returns focus to the button; a click outside closes", async () => {
    menu();
    const button = screen.getByRole("button", { name: "More" });
    await userEvent.click(button);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(button).toHaveFocus();
    await userEvent.click(button);
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("closes after a menu item runs", async () => {
    menu();
    await userEvent.click(screen.getByRole("button", { name: "More" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Second" }));
    expect(screen.queryByRole("menu")).toBeNull();
    expect(screen.getByRole("button", { name: "More" })).toHaveAttribute("aria-expanded", "false");
  });
});

describe("Sidebar", () => {
  it("marks where you are and switches tab or dataset", async () => {
    const { props } = sidebar();
    expect(screen.getByRole("button", { name: "Dashboard" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: /Retail Sales/ })).toHaveAttribute("aria-current", "true");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(props.onTab).toHaveBeenCalledWith("ask");
    await userEvent.click(screen.getByRole("button", { name: /SaaS Metrics/ }));
    expect(props.onChooseDataset).toHaveBeenCalledWith("d2");
    expect(screen.getByText(/1 document in Ask/)).toBeInTheDocument();
  });

  it("keeps the tour's anchors on screen", () => {
    const { container } = sidebar();
    for (const anchor of ["upload", "connect", "templates", "ask"]) {
      expect(container.querySelector(`[data-tour="${anchor}"]`), anchor).toBeTruthy();
    }
  });

  it("uploads the chosen file", async () => {
    const { props, container } = sidebar();
    const file = new File(["a,b\n1,2"], "x.csv", { type: "text/csv" });
    await userEvent.upload(container.querySelector('input[type="file"]'), file);
    expect(props.onUpload).toHaveBeenCalledWith(file);
  });

  it("hides editor and admin items from a viewer", () => {
    sidebar({ canEdit: false, isAdmin: false });
    expect(screen.queryByRole("button", { name: /Upload/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Team" })).toBeNull();
  });

  it("chooses a theme and logs out from the account menu", async () => {
    const { props } = sidebar();
    await userEvent.click(screen.getByRole("button", { name: "Account" }));
    expect(screen.getByRole("menuitemcheckbox", { name: /Match system/ })).toHaveAttribute("aria-checked", "true");
    await userEvent.click(screen.getByRole("menuitemcheckbox", { name: /Dark/ }));
    expect(props.onTheme).toHaveBeenCalledWith("dark");
    await userEvent.click(screen.getByRole("menuitem", { name: /Log out/ }));
    expect(props.onLogout).toHaveBeenCalled();
  });

  it("names every control (collapsed icons included)", async () => {
    const { container } = sidebar({ collapsed: true });
    const r = await axe.run(container, { resultTypes: ["violations"],
      runOnly: { type: "rule", values: ["button-name", "aria-valid-attr-value", "aria-allowed-attr"] } });
    expect(r.violations.map((v) => v.id)).toEqual([]);
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toBeInTheDocument();
  });
});

describe("human dates", () => {
  it("formats days, months and ranges without a timezone in sight", () => {
    expect(formatDate("2026-10-28")).toBe("28 Oct 2026");
    expect(formatDate("2026-10")).toBe("Oct 2026");
    expect(formatDate("2026-10-01T00:00:00")).toBe("1 Oct 2026");
    expect(formatDate("2026-Q4")).toBe("2026-Q4");
    expect(formatRange("2026-01-01", "2026-10-28")).toBe("1 Jan – 28 Oct 2026");
    expect(formatRange("2025-11-01", "2026-02-28")).toBe("1 Nov 2025 – 28 Feb 2026");
    expect(formatRange("2026-10", "2026-10")).toBe("Oct 2026");
    expect(formatRange("2026-03", null)).toBe("from Mar 2026");
  });

  it("keeps axis ticks short", () => {
    expect(formatTick("2026-10")).toBe("Oct 2026");
    expect(formatTick("2026-10-28")).toBe("28 Oct");
    expect(formatTick("2026-Q4")).toBe("2026-Q4");
  });
});
