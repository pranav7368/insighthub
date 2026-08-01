import { describe, expect, it } from "vitest";

import {
  SECTIONS, SECTION_KEYS, moveKey, moveKeyByStep, orderSections, resolveOrder, sectionLabel,
} from "./sections";

const entries = (...keys) => keys.map((key) => ({ key, node: key }));
const keysOf = (list) => list.map((e) => e.key);

describe("the canonical section list", () => {
  it("has no duplicate keys", () => {
    expect(new Set(SECTION_KEYS).size).toBe(SECTION_KEYS.length);
  });

  it("labels every key", () => {
    for (const key of SECTION_KEYS) {
      expect(sectionLabel(key)).toBeTruthy();
      expect(sectionLabel(key)).not.toBe(key);
    }
  });

  it("falls back to the key for something unknown", () => {
    expect(sectionLabel("not_a_section")).toBe("not_a_section");
  });

  it("stays in sync with the pairs it is derived from", () => {
    expect(SECTION_KEYS).toEqual(SECTIONS.map(([k]) => k));
  });
});

describe("orderSections", () => {
  it("leaves things alone when no order is saved", () => {
    const list = entries("kpis", "growth", "forecast");
    expect(orderSections(list, [])).toBe(list);
    expect(orderSections(list, undefined)).toBe(list);
  });

  it("puts listed sections first, in the order given", () => {
    const list = entries("kpis", "growth", "forecast", "map");
    expect(keysOf(orderSections(list, ["map", "forecast"])))
      .toEqual(["map", "forecast", "kpis", "growth"]);
  });

  it("keeps unlisted sections in their natural relative order", () => {
    // this is what lets a template highlight a few sections without having to
    // enumerate all fourteen
    const list = entries("kpis", "metrics", "drivers", "growth", "insights");
    expect(keysOf(orderSections(list, ["growth"])))
      .toEqual(["growth", "kpis", "metrics", "drivers", "insights"]);
  });

  it("ignores keys in the order that are not present", () => {
    const list = entries("kpis", "growth");
    expect(keysOf(orderSections(list, ["map", "growth"]))).toEqual(["growth", "kpis"]);
  });

  it("never drops or duplicates a section", () => {
    const list = entries(...SECTION_KEYS);
    const ordered = orderSections(list, ["profile", "map", "kpis"]);
    expect(ordered).toHaveLength(SECTION_KEYS.length);
    expect(new Set(keysOf(ordered)).size).toBe(SECTION_KEYS.length);
  });
});

describe("resolveOrder", () => {
  it("expands a partial order into every key", () => {
    const resolved = resolveOrder(["forecast", "kpis"]);
    expect(resolved).toHaveLength(SECTION_KEYS.length);
    expect(resolved.slice(0, 2)).toEqual(["forecast", "kpis"]);
    expect(new Set(resolved)).toEqual(new Set(SECTION_KEYS));
  });

  it("returns the natural order when nothing is saved", () => {
    expect(resolveOrder([])).toEqual(SECTION_KEYS);
  });
});

describe("moveKey", () => {
  const base = ["a", "b", "c", "d"];

  it("drops after the target when moving down", () => {
    expect(moveKey(base, "a", "c")).toEqual(["b", "c", "a", "d"]);
  });

  it("drops before the target when moving up", () => {
    expect(moveKey(base, "d", "b")).toEqual(["a", "d", "b", "c"]);
  });

  it("is a no-op onto itself", () => {
    expect(moveKey(base, "b", "b")).toEqual(base);
  });

  it("is a no-op for keys it does not know", () => {
    expect(moveKey(base, "zz", "b")).toEqual(base);
    expect(moveKey(base, "a", "zz")).toEqual(base);
  });

  it("preserves length and membership", () => {
    const moved = moveKey(base, "a", "d");
    expect(moved).toHaveLength(base.length);
    expect(new Set(moved)).toEqual(new Set(base));
  });

  it("does not mutate its input", () => {
    const original = [...base];
    moveKey(base, "a", "c");
    expect(base).toEqual(original);
  });
});

describe("moveKeyByStep", () => {
  // the full order includes hidden sections; visible is what is on screen
  const full = ["a", "hidden1", "b", "hidden2", "c"];
  const visible = ["a", "b", "c"];

  it("swaps with the next VISIBLE neighbour, not the next key", () => {
    // moving 'a' down must land it past 'b', not past the hidden section —
    // otherwise the arrow appears to do nothing
    const moved = moveKeyByStep(full, "a", visible, 1);
    expect(moved.indexOf("a")).toBeGreaterThan(moved.indexOf("b"));
  });

  it("moves up past the previous visible neighbour", () => {
    const moved = moveKeyByStep(full, "c", visible, -1);
    expect(moved.indexOf("c")).toBeLessThan(moved.indexOf("b"));
  });

  it("is a no-op at the top", () => {
    expect(moveKeyByStep(full, "a", visible, -1)).toEqual(full);
  });

  it("is a no-op at the bottom", () => {
    expect(moveKeyByStep(full, "c", visible, 1)).toEqual(full);
  });

  it("keeps hidden sections in the list so they return to place", () => {
    const moved = moveKeyByStep(full, "a", visible, 1);
    expect(moved).toContain("hidden1");
    expect(moved).toContain("hidden2");
    expect(moved).toHaveLength(full.length);
  });
});
