import { humanLabel } from "../format";

// Active cross-filters (from clicking charts or the sidebar) shown as
// removable chips, so it's always clear what the dashboard is scoped to.
export default function FilterChips({ filters, onRemove, onClearAll }) {
  const entries = Object.entries(filters || {});
  if (!entries.length) return null;
  return (
    <div className="filter-chips">
      <span className="filter-chips__label">Filtered to</span>
      {entries.map(([k, v]) => (
        <button className="chip" key={k} onClick={() => onRemove(k)} title="Remove filter">
          {humanLabel(k)}: <b>{v}</b> <span className="chip__x">×</span>
        </button>
      ))}
      {entries.length > 1 && (
        <button className="chip chip--clear" onClick={onClearAll}>Clear all</button>
      )}
    </div>
  );
}
