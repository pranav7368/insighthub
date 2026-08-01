// Dashboard sections: the canonical list, their labels, and the ordering rules
// shared by the private dashboard, the public share view and the Customize menu.
//
// Keep the keys in sync with SECTION_KEYS on the backend (analytics/views.py) —
// a saved view's `section_order` / `hidden_sections` are validated against that
// set, so an unknown key here would be rejected on save.

export const SECTIONS = [
  ["kpis", "KPI cards"],
  ["metrics", "Certified metrics"],
  ["drivers", "What changed"],
  ["growth", "Growth strip"],
  ["insights", "Key insights"],
  ["narrative", "AI narrative"],
  ["forecast", "Forecast"],
  ["breakdowns", "Breakdowns"],
  ["map", "Map"],
  ["pareto", "Pareto (80/20)"],
  ["treemap", "Treemap"],
  ["correlations", "Correlations"],
  ["distributions", "Distributions"],
  ["profile", "Data profile"],
];

// natural (as-authored) order — the fallback whenever a view says nothing
export const SECTION_KEYS = SECTIONS.map(([key]) => key);

const LABELS = Object.fromEntries(SECTIONS);
export const sectionLabel = (key) => LABELS[key] || key;

/**
 * Apply a saved order to a list of `{ key, node }` entries.
 *
 * `order` may be partial: listed sections come first in the order given, and
 * anything unlisted keeps its natural relative position afterwards. That lets
 * an industry template highlight a handful of sections without having to
 * enumerate all of them, while a user-dragged order (which lists every key)
 * is honoured exactly.
 */
export function orderSections(entries, order) {
  if (!order || order.length === 0) return entries;
  const rank = new Map(order.map((key, i) => [key, i]));
  const listed = entries
    .filter((e) => rank.has(e.key))
    .sort((a, b) => rank.get(a.key) - rank.get(b.key));
  const rest = entries.filter((e) => !rank.has(e.key));
  return [...listed, ...rest];
}

/** The full key order implied by a (possibly partial, possibly empty) saved order. */
export function resolveOrder(order) {
  return orderSections(SECTION_KEYS.map((key) => ({ key })), order).map((e) => e.key);
}

/** Move `movingKey` to `targetKey`'s slot, preserving drag direction semantics. */
export function moveKey(keys, movingKey, targetKey) {
  const fromIdx = keys.indexOf(movingKey);
  const toIdx = keys.indexOf(targetKey);
  if (fromIdx < 0 || toIdx < 0 || fromIdx === toIdx) return keys;
  const list = keys.slice();
  const [item] = list.splice(fromIdx, 1);
  // dragging downwards drops *after* the target, upwards drops *before* it
  list.splice(list.indexOf(targetKey) + (fromIdx < toIdx ? 1 : 0), 0, item);
  return list;
}

/**
 * Keyboard equivalent of a drag: swap a section with its neighbour among the
 * sections actually on screen, so ↑/↓ never appears to do nothing because the
 * adjacent section happens to be hidden.
 */
export function moveKeyByStep(keys, movingKey, visibleKeys, step) {
  const pos = visibleKeys.indexOf(movingKey);
  const neighbour = visibleKeys[pos + step];
  if (pos < 0 || neighbour === undefined) return keys;
  return moveKey(keys, movingKey, neighbour);
}
