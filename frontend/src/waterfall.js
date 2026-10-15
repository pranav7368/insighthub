/**
 * Waterfall: a start total, signed steps, an end total. Each step floats from
 * the running total, so the bars visibly add up to the end — the picture of a
 * reconciliation. Steps are stacked on an invisible base.
 */
export function waterfallRows(start, steps, end) {
  const rows = [{ label: start.label, kind: "total", base: 0, bar: start.value, value: start.value }];
  let run = start.value;
  for (const s of steps) {
    const next = run + s.delta;
    rows.push({
      label: s.label, kind: s.delta >= 0 ? "up" : "down", base: Math.min(run, next),
      bar: Math.abs(s.delta), value: s.delta, step: s,
    });
    run = next;
  }
  rows.push({ label: end.label, kind: "total", base: 0, bar: end.value, value: end.value });
  return rows;
}

export function domainOf(rows) {
  // zoom to where the movement is: a 3% change drawn from zero is invisible
  const tops = rows.map((r) => r.base + r.bar);
  const lows = rows.map((r) => (r.kind === "total" ? r.bar : r.base));
  let lo = Math.min(...lows);
  let hi = Math.max(...tops);
  const pad = (hi - lo) * 0.25 || Math.abs(hi) * 0.1 || 1;
  lo = lo - pad;
  if (lo < 0 && Math.min(...lows) >= 0) lo = 0;
  return [lo, hi + pad * 0.4];
}

