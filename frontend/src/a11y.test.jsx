import { render } from "@testing-library/react";
import axe from "axe-core";
import { describe, expect, it, vi } from "vitest";

import FilterBar from "./components/FilterBar";
import TourOverlay from "./components/TourOverlay";
import ViewsBar from "./components/ViewsBar";

/**
 * Accessibility regression tests.
 *
 * A full axe pass over the running app is driven separately in a real browser
 * (which is the only way to check colour contrast, since jsdom computes no
 * layout or colour). These cover the structural rules jsdom *can* see —
 * labels, accessible names, roles — because those are the ones a refactor
 * silently breaks: renaming a class does not remove a label, but rewriting a
 * form does.
 *
 * Both defects these guard against were real, found by scanning the live app:
 * every filter control was an unlabelled combo box to a screen reader, and the
 * dataset/view pickers had no accessible name at all.
 */
async function violations(container, rules) {
  const results = await axe.run(container, {
    resultTypes: ["violations"],
    runOnly: { type: "rule", values: rules },
  });
  return results.violations.map((v) => `${v.id}: ${v.nodes.length} node(s)`);
}

async function readSource(name) {
  const { readFileSync } = await import("node:fs");
  const { resolve } = await import("node:path");
  return readFileSync(resolve(process.cwd(), "src", name), "utf-8");
}

const STRUCTURAL = ["label", "select-name", "button-name", "aria-valid-attr-value",
                    "aria-required-attr", "duplicate-id-aria"];

describe("accessibility — form controls carry names", () => {
  it("FilterBar labels every select and date input", async () => {
    const { container } = render(
      <FilterBar
        filterOptions={{ region: { values: ["North", "South"] } }}
        activeFilters={{}}
        onFilterChange={vi.fn()}
        dateFrom="" dateTo=""
        onDateFromChange={vi.fn()} onDateToChange={vi.fn()}
        onReset={vi.fn()}
      />
    );
    expect(await violations(container, STRUCTURAL)).toEqual([]);
  });

  it("FilterBar associates each label with its control, not just places it nearby", () => {
    const { container } = render(
      <FilterBar
        filterOptions={{ region: { values: ["North"] } }}
        activeFilters={{}}
        onFilterChange={vi.fn()}
        dateFrom="" dateTo=""
        onDateFromChange={vi.fn()} onDateToChange={vi.fn()}
        onReset={vi.fn()}
      />
    );
    // a <label> naming nothing is invisible to assistive technology
    for (const label of container.querySelectorAll("label")) {
      const target = label.getAttribute("for");
      expect(target, `"${label.textContent}" names no control`).toBeTruthy();
      expect(container.querySelector(`#${CSS.escape(target)}`)).toBeTruthy();
    }
  });

  it("ViewsBar names the saved-view picker", async () => {
    const { container } = render(
      <ViewsBar
        views={[]} activeViewId={null} dirty={false} hiddenSections={[]} arranging={false}
        onApply={vi.fn()} onToggleSection={vi.fn()} onSave={vi.fn()} onUpdate={vi.fn()}
        onDelete={vi.fn()} onSetDefault={vi.fn()} onToggleArrange={vi.fn()}
      />
    );
    expect(await violations(container, STRUCTURAL)).toEqual([]);
  });

  it("the tour dialog is announced as a dialog with a name", async () => {
    const { container } = render(
      <TourOverlay
        steps={[{ id: "a", title: "Welcome", body: "hello" }]}
        onFinish={vi.fn()}
      />
    );
    const dialog = container.querySelector('[role="dialog"]');
    expect(dialog).toBeTruthy();
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(dialog.getAttribute("aria-labelledby")).toBeTruthy();
    expect(await violations(container, STRUCTURAL)).toEqual([]);
  });
});

describe("accessibility — colour tokens", () => {
  /**
   * Contrast itself is verified in a real browser; this only guards the
   * decision that produced the tokens, so nobody "simplifies" the text
   * colours back onto the chart palette. --status-* are tuned as chart MARKS
   * and measure 2.76:1 and 3.27:1 as text, well under 4.5:1.
   */
  it("keeps text colours separate from the chart palette", async () => {
    // import.meta.url is an http URL under vitest, so resolve from cwd
    const theme = await readSource("theme.css");
    for (const token of ["--text-good", "--text-critical", "--accent-fill"]) {
      expect(theme, `${token} is what keeps text off the chart palette`).toContain(token);
    }
  });

  it("does not use a chart mark colour as button-fill text", async () => {
    const app = await readSource("App.css");
    // white text on --series-1 measures 4.42:1 (light) and 3.64:1 (dark)
    const offenders = app
      .split("\n")
      .filter((line) => line.includes("background: var(--series-1)") && line.includes("#fff"));
    expect(offenders).toEqual([]);
  });
});
