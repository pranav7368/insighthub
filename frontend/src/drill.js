// The drill context — one object describes "which number are we looking at":
//   { measure, agg, filters: {col: value, ...}, date_from, date_to, grain, tab, dimension }
// Every chart emits one on click, the inspector renders one, and the URL
// stores one, so drilling is the same operation everywhere.
import { humanLabel } from "./format";

export const AGG_LABELS = { sum: "Total", avg: "Average", count: "Count", min: "Minimum", max: "Maximum", median: "Median" };
export const GRAINS = ["day", "week", "month", "quarter", "year"];

export function makeCtx({ measure = null, agg = "sum", filters = {}, date_from = null, date_to = null,
  grain = "month", tab = "overview", dimension = null, compare = "previous" } = {}) {
  return { measure, agg, filters: { ...filters }, date_from, date_to, grain, tab, dimension, compare };
}

/** One step deeper: pin `dim = value` (insertion order is the drill order). */
export const drillInto = (ctx, dim, value) =>
  ({ ...ctx, filters: { ...ctx.filters, [dim]: value }, tab: "overview", dimension: null });

/** Narrow to one period, given the bounds the backend sent with the point. */
export const drillPeriod = (ctx, from, to) => ({ ...ctx, date_from: from, date_to: to, tab: "overview" });

export function periodLabel(from, to) {
  if (!from && !to) return null;
  if (from && to) return from === to ? from : `${from} → ${to}`;
  return from ? `from ${from}` : `until ${to}`;
}

/**
 * Breadcrumbs: the measure, then the period (if any), then each pinned filter
 * in the order it was drilled. Crumb i navigates back to "the first i+1".
 */
export function crumbs(ctx) {
  const out = [{ label: ctx.agg === "count" ? "Row count" : humanLabel(ctx.measure || "value"), kind: "root" }];
  const period = periodLabel(ctx.date_from, ctx.date_to);
  if (period) out.push({ label: period, kind: "period" });
  for (const [k, v] of Object.entries(ctx.filters || {})) out.push({ label: `${humanLabel(k)}: ${v}`, kind: "filter", key: k });
  return out;
}

export function truncateCtx(ctx, index) {
  const hasPeriod = Boolean(ctx.date_from || ctx.date_to);
  const keepPeriod = hasPeriod && index >= 1;
  const nFilters = Math.max(0, index - (hasPeriod ? 1 : 0));
  const filters = Object.fromEntries(Object.entries(ctx.filters || {}).slice(0, nFilters));
  return {
    ...ctx, filters, tab: "overview", dimension: null,
    date_from: keepPeriod ? ctx.date_from : null,
    date_to: keepPeriod ? ctx.date_to : null,
  };
}

export function pctText(pct) {
  if (pct == null || !Number.isFinite(pct)) return null;
  return `${pct > 0 ? "▲" : pct < 0 ? "▼" : "▬"} ${Math.abs(pct).toFixed(1)}%`;
}

// ---------------------------------------------------------- URL state ---
// ?ds=<dataset>&m=<measure>&from=&to=&f=<json filters>&ins=<json ctx>
// Shareable, bookmarkable, and the browser back button walks back up a drill.

const isPlainObject = (v) => Boolean(v) && typeof v === "object" && !Array.isArray(v);

function parseJson(raw, fallback) {
  if (!raw) return fallback;
  try {
    const v = JSON.parse(raw);
    return isPlainObject(v) ? v : fallback;
  } catch {
    return fallback;
  }
}

export function readUrlState(search) {
  const q = new URLSearchParams(search);
  const ins = parseJson(q.get("ins"), null);
  return {
    datasetId: q.get("ds") || null,
    measure: q.get("m") || null,
    dateFrom: q.get("from") || undefined,
    dateTo: q.get("to") || undefined,
    filters: parseJson(q.get("f"), {}),
    inspect: ins ? makeCtx({ ...ins, filters: isPlainObject(ins.filters) ? ins.filters : {} }) : null,
  };
}

export function buildUrlSearch({ datasetId, measure, dateFrom, dateTo, filters, inspect }) {
  const q = new URLSearchParams();
  if (datasetId) q.set("ds", datasetId);
  if (measure) q.set("m", measure);
  if (dateFrom) q.set("from", dateFrom);
  if (dateTo) q.set("to", dateTo);
  if (filters && Object.keys(filters).length) q.set("f", JSON.stringify(filters));
  if (inspect) {
    const { measure: im, agg, filters: f, date_from, date_to, grain, tab, dimension, compare } = inspect;
    q.set("ins", JSON.stringify({ measure: im, agg, filters: f, date_from, date_to, grain, tab, dimension, compare }));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}
