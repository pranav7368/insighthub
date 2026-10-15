import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { describe, expect, it, vi } from "vitest";

import { buildCommands, scoreMatch, searchCommands } from "../palette";
import CommandPalette from "./CommandPalette";
import DataMenu from "./DataMenu";

const DASH = {
  kpis: [{ column: "revenue" }, { column: "units_sold" }],
  date_column: "date",
  filter_options: { region: { values: ["North", "South"] }, product: { values: ["Widget"] } },
  data_profile: { date_span: { from: "2025-01-01", to: "2026-10-28" } },
};

const handlers = () => ({
  inspect: vi.fn(), applyView: vi.fn(), scrollTo: vi.fn(), clearFilters: vi.fn(),
  setDates: vi.fn(), exportFile: vi.fn(), arrange: vi.fn(),
});

describe("palette ranking", () => {
  it("needs every word and prefers word starts", () => {
    expect(scoreMatch("rev", "Revenue — details")).toBeGreaterThan(scoreMatch("rev", "Average revenue"));
    expect(scoreMatch("north rev", "Region: North")).toBeNull();
    expect(scoreMatch("region north", "Region: North")).not.toBeNull();
    expect(scoreMatch("why", "Why did Revenue change?")).toBeGreaterThan(scoreMatch("why", "Somewhy"));
  });

  it("prefers a whole word to a prefix", () => {
    const cmds = buildCommands({ dashboard: DASH, on: handlers(), visibleSections: ["tree", "treemap"] });
    expect(searchCommands(cmds, "go to tree")[0].label).toBe("Go to Decomposition tree");
    expect(searchCommands(cmds, "treemap")[0].label).toBe("Go to Treemap");
  });

  it("lists segments only once you type", () => {
    const cmds = buildCommands({ dashboard: DASH, on: handlers() });
    expect(searchCommands(cmds, "").some((c) => c.group === "Segments")).toBe(false);
    expect(searchCommands(cmds, "north")[0].label).toBe("Region: North");
  });
});

describe("command building", () => {
  it("offers numbers, segments, sections, views and actions, each wired to its handler", () => {
    const on = handlers();
    const cmds = buildCommands({
      dashboard: DASH, on, filters: { product: "Widget" },
      views: [{ view_id: "v1", name: "Board pack", is_default: true }],
      visibleSections: ["kpis", "tree"],
    });
    const byLabel = Object.fromEntries(cmds.map((c) => [c.label, c]));
    byLabel["Why did Revenue change?"].run();
    expect(on.inspect).toHaveBeenCalledWith({ measure: "revenue", tab: "change" });
    byLabel["Region: North"].run();
    // a segment keeps the dashboard's own filters
    expect(on.inspect).toHaveBeenLastCalledWith({ filters: { product: "Widget", region: "North" } });
    byLabel["Go to Decomposition tree"].run();
    expect(on.scrollTo).toHaveBeenCalledWith("tree");
    expect(byLabel["Go to Map"]).toBeUndefined();          // not on the page
    byLabel["View: Board pack"].run();
    expect(on.applyView).toHaveBeenCalled();
    byLabel["Show year to date"].run();
    expect(on.setDates).toHaveBeenCalledWith("2026-01-01", "2026-10-28");
    expect(byLabel["Clear all filters"]).toBeDefined();
  });

  it("does not offer 'why did it change' without a date column", () => {
    const cmds = buildCommands({ dashboard: { ...DASH, date_column: null }, on: handlers() });
    expect(cmds.some((c) => c.label.startsWith("Why did"))).toBe(false);
  });
});

describe("CommandPalette", () => {
  it("is keyboard driven: type, arrow, enter", async () => {
    const on = handlers();
    const onClose = vi.fn();
    render(<CommandPalette commands={buildCommands({ dashboard: DASH, on })} onClose={onClose} />);
    const input = screen.getByRole("combobox");
    expect(input).toHaveFocus();
    await userEvent.type(input, "units");
    expect(screen.getAllByRole("option")[0]).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{ArrowDown}{Enter}");
    expect(onClose).toHaveBeenCalled();
    expect(on.inspect).toHaveBeenCalledWith(expect.objectContaining({ measure: "units_sold" }));
  });

  it("says when nothing matches, and Escape closes", async () => {
    const onClose = vi.fn();
    render(<CommandPalette commands={buildCommands({ dashboard: DASH, on: handlers() })} onClose={onClose} />);
    await userEvent.type(screen.getByRole("combobox"), "zzzz");
    expect(screen.getByText(/Nothing matches/)).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });

  it("follows the combobox pattern", async () => {
    const { container } = render(<CommandPalette commands={buildCommands({ dashboard: DASH, on: handlers() })} onClose={vi.fn()} />);
    const r = await axe.run(container, { resultTypes: ["violations"],
      runOnly: { type: "rule", values: ["aria-required-children", "aria-valid-attr-value", "aria-allowed-attr", "list", "listitem"] } });
    expect(r.violations.map((v) => v.id)).toEqual([]);
  });
});

describe("DataMenu", () => {
  const items = (run) => [{ label: "Open details", run }, { label: "See the rows", run: vi.fn() }];

  it("focuses the first item, moves with arrows, runs on click", async () => {
    const run = vi.fn();
    const onClose = vi.fn();
    render(<DataMenu x={10} y={10} title="Region: North" items={items(run)} onClose={onClose} />);
    const [first, second] = screen.getAllByRole("menuitem");
    expect(first).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}");
    expect(second).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}");
    expect(first).toHaveFocus();                   // wraps
    await userEvent.click(first);
    expect(run).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it("closes on Escape and on a click elsewhere", () => {
    const onClose = vi.fn();
    render(<DataMenu x={10} y={10} title="t" items={items(vi.fn())} onClose={onClose} />);
    fireEvent.keyDown(window, { key: "Escape" });
    fireEvent.mouseDown(document.body);
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
