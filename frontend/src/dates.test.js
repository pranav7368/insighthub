import { describe, expect, it } from "vitest";
import { presetFrom } from "./dates";
import { domainOf, waterfallRows } from "./waterfall";

describe("date presets", () => {
  it("period-to-date presets start on the right day", () => {
    expect(presetFrom("2026-10-28", "MTD")).toBe("2026-10-01");
    expect(presetFrom("2026-10-28", "QTD")).toBe("2026-10-01");
    expect(presetFrom("2026-08-15", "QTD")).toBe("2026-07-01");
    expect(presetFrom("2026-10-28", "YTD")).toBe("2026-01-01");
  });

  it("rolling presets cross year boundaries", () => {
    expect(presetFrom("2026-02-10", "3M")).toBe("2025-12-01");
    expect(presetFrom("2026-10-28", "12M")).toBe("2025-11-01");
    expect(presetFrom("2026-01-31", "6M")).toBe("2025-08-01");
  });

  it("does not shift a day in timezones east of UTC", () => {
    // the old implementation went through toISOString and returned the 30th
    expect(presetFrom("2026-10-01", "MTD")).toBe("2026-10-01");
  });
});

describe("waterfall", () => {
  const rows = waterfallRows({ label: "Feb", value: 400 },
    [{ label: "North", delta: 300 }, { label: "South", delta: -50 }], { label: "Mar", value: 650 });

  it("each step floats from the running total and lands on the end", () => {
    expect(rows.map((r) => [r.kind, r.base, r.bar])).toEqual([
      ["total", 0, 400], ["up", 400, 300], ["down", 650, 50], ["total", 0, 650],
    ]);
  });

  it("zooms the axis to where the movement is", () => {
    const [lo, hi] = domainOf(rows);
    expect(lo).toBeGreaterThan(0);
    expect(lo).toBeLessThan(400);
    expect(hi).toBeGreaterThan(700);
  });
});
