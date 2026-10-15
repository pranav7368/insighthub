// Command palette: the commands a dashboard offers, and how a typed query
// ranks them. Pure functions — the palette component only renders and runs.
import { humanLabel } from "./format";
import { presetFrom } from "./dates";
import { SECTIONS, sectionLabel } from "./sections";

export const GROUPS = ["Numbers", "Segments", "Go to", "Views", "Actions"];
const MAX_SEGMENT_VALUES = 200;

/**
 * Score `text` against `query`, or null when it does not match. Every query
 * word must appear; a word matching at the start of a word counts three times
 * a match in the middle, and a label that starts with the whole query wins.
 */
export function scoreMatch(query, text) {
  const q = query.trim().toLowerCase();
  if (!q) return 0;
  const t = text.toLowerCase();
  const edge = (ch) => ch === undefined || /[\s:—(·?-]/.test(ch);
  // a label that starts with the query; most when the query ends a word
  let score = !t.startsWith(q) ? 0 : edge(t[q.length]) ? 10 : 2;
  for (const word of q.split(/\s+/)) {
    const at = t.indexOf(word);
    if (at < 0) return null;
    score += edge(t[at - 1]) ? 3 : 1;
    // a whole word beats a prefix: "tree" means the tree, not "treemap"
    if (edge(t[at - 1]) && edge(t[at + word.length])) score += 3;
  }
  return score - t.length / 1000;   // shorter labels win ties
}

/** Commands matching `query`, best first (grouped order when empty). */
export function searchCommands(commands, query, limit = 50) {
  const rank = (c) => GROUPS.indexOf(c.group);
  if (!query.trim()) {
    // segment values are only worth listing once the user types
    return commands.filter((c) => c.group !== "Segments")
      .sort((a, b) => rank(a) - rank(b)).slice(0, limit);
  }
  return commands
    .map((c) => ({ c, s: scoreMatch(query, `${c.label} ${c.keywords || ""}`) }))
    .filter((x) => x.s !== null)
    .sort((a, b) => b.s - a.s || rank(a.c) - rank(b.c))
    .slice(0, limit)
    .map((x) => x.c);
}

/**
 * Everything the dashboard can do, as commands. `on` supplies the handlers:
 * inspect(partialSlice), applyView(view), scrollTo(sectionKey),
 * clearFilters(), setDates(from, to), exportFile(kind), arrange().
 */
export function buildCommands({ dashboard, views = [], visibleSections = [], filters = {}, on }) {
  const out = [];
  if (!dashboard) return out;
  const dated = Boolean(dashboard.date_column);

  for (const k of dashboard.kpis || []) {
    const name = humanLabel(k.column);
    out.push({ id: `num:${k.column}`, group: "Numbers", label: `${name} — details`, hint: "trend, spread, contributors",
      run: () => on.inspect({ measure: k.column }) });
    if (dated) {
      out.push({ id: `why:${k.column}`, group: "Numbers", label: `Why did ${name} change?`, hint: "waterfall + drivers",
        keywords: "explain change variance drop rise", run: () => on.inspect({ measure: k.column, tab: "change" }) });
    }
    out.push({ id: `rows:${k.column}`, group: "Numbers", label: `${name} — show the rows`, keywords: "records data table",
      run: () => on.inspect({ measure: k.column, tab: "records" }) });
  }

  for (const [dim, opt] of Object.entries(dashboard.filter_options || {})) {
    for (const value of (opt.values || []).slice(0, MAX_SEGMENT_VALUES)) {
      out.push({ id: `seg:${dim}:${value}`, group: "Segments", label: `${humanLabel(dim)}: ${value}`,
        hint: "open details", run: () => on.inspect({ filters: { ...filters, [dim]: String(value) } }) });
    }
  }

  const visible = new Set(visibleSections);
  for (const [key] of SECTIONS) {
    if (!visible.has(key)) continue;
    out.push({ id: `go:${key}`, group: "Go to", label: `Go to ${sectionLabel(key)}`, run: () => on.scrollTo(key) });
  }

  for (const v of views) {
    out.push({ id: `view:${v.view_id}`, group: "Views", label: `View: ${v.name}`, hint: v.is_default ? "default" : "",
      run: () => on.applyView(v) });
  }

  const last = dashboard.data_profile?.date_span?.to;
  if (last) {
    for (const [p, label] of [["MTD", "month to date"], ["QTD", "quarter to date"], ["YTD", "year to date"], ["12M", "last 12 months"]]) {
      out.push({ id: `date:${p}`, group: "Actions", label: `Show ${label}`, keywords: `date range ${p}`,
        run: () => on.setDates(presetFrom(last, p), last.slice(0, 10)) });
    }
  }
  if (Object.keys(filters).length) {
    out.push({ id: "clear", group: "Actions", label: "Clear all filters", keywords: "reset", run: () => on.clearFilters() });
  }
  out.push({ id: "pdf", group: "Actions", label: "Export PDF", keywords: "download print", run: () => on.exportFile("pdf") });
  out.push({ id: "csv", group: "Actions", label: "Download the data as CSV", keywords: "export", run: () => on.exportFile("csv") });
  out.push({ id: "arrange", group: "Actions", label: "Arrange sections", keywords: "layout reorder drag",
    run: () => on.arrange() });
  return out;
}
