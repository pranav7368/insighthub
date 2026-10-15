import { describe, expect, it } from "vitest";
import {
  buildUrlSearch, crumbs, drillInto, drillPeriod, makeCtx, pctText, readUrlState, truncateCtx,
} from "./drill";

describe("drill context", () => {
  const base = makeCtx({ measure: "revenue" });

  it("drilling pins filters in order and returns to the overview", () => {
    const c = drillInto(drillInto({ ...base, tab: "breakdown" }, "region", "North"), "city", "Delhi");
    expect(Object.entries(c.filters)).toEqual([["region", "North"], ["city", "Delhi"]]);
    expect(c.tab).toBe("overview");
  });

  it("breadcrumbs read measure › period › filters", () => {
    const c = drillInto(drillPeriod(base, "2025-03", "2025-03"), "region", "North");
    expect(crumbs(c).map((x) => x.label)).toEqual(["Revenue", "2025-03", "Region: North"]);
    expect(crumbs(makeCtx({ agg: "count" }))[0].label).toBe("Row count");
  });

  it("clicking a crumb walks back up to that level", () => {
    const c = drillInto(drillInto(drillPeriod(base, "2025-01", "2025-03"), "region", "North"), "city", "Delhi");
    expect(truncateCtx(c, 0)).toMatchObject({ filters: {}, date_from: null, date_to: null });
    expect(truncateCtx(c, 1)).toMatchObject({ filters: {}, date_from: "2025-01", date_to: "2025-03" });
    expect(truncateCtx(c, 2).filters).toEqual({ region: "North" });
    // without a period, crumb 1 is the first filter
    const noPeriod = drillInto(drillInto(base, "region", "North"), "city", "Delhi");
    expect(truncateCtx(noPeriod, 1).filters).toEqual({ region: "North" });
  });

  it("formats percentage changes with a direction", () => {
    expect(pctText(12.345)).toBe("▲ 12.3%");
    expect(pctText(-4)).toBe("▼ 4.0%");
    expect(pctText(null)).toBeNull();
  });
});

describe("URL state", () => {
  it("round-trips the dashboard and the open inspector", () => {
    const inspect = drillInto(makeCtx({ measure: "revenue", grain: "week" }), "region", "North & South");
    const search = buildUrlSearch({
      datasetId: "ds_1", measure: "revenue", dateFrom: "2025-01", dateTo: undefined,
      filters: { product: "Widget" }, inspect,
    });
    const back = readUrlState(search);
    expect(back).toMatchObject({
      datasetId: "ds_1", measure: "revenue", dateFrom: "2025-01", filters: { product: "Widget" },
    });
    expect(back.inspect).toMatchObject({ measure: "revenue", grain: "week", filters: { region: "North & South" } });
  });

  it("ignores malformed or hostile values instead of crashing", () => {
    const s = readUrlState("?ds=x&f=%5B1%5D&ins=not-json");
    expect(s.filters).toEqual({});
    expect(s.inspect).toBeNull();
    expect(readUrlState('?ins={"filters":[1,2]}').inspect.filters).toEqual({});
  });

  it("an empty state writes an empty query", () => {
    expect(buildUrlSearch({})).toBe("");
  });
});
