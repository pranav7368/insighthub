import { humanLabel } from "../format";

export default function FilterBar({
  filterOptions, activeFilters, onFilterChange,
  dateFrom, dateTo, onDateFromChange, onDateToChange, onReset,
}) {
  const dims = Object.entries(filterOptions ?? {});
  const hasActive = Object.values(activeFilters).some(Boolean) || dateFrom || dateTo;
  return (
    <aside className="filter-bar">
      <div className="filter-bar__title">Filters</div>
      {dims.map(([name, meta]) => (
        <div className="filter-field" key={name}>
          <label>{humanLabel(name)}</label>
          <select value={activeFilters[name] ?? ""} onChange={(e) => onFilterChange(name, e.target.value || undefined)}>
            <option value="">All</option>
            {meta.values.map((v) => <option key={v} value={v}>{v}</option>)}
          </select>
        </div>
      ))}
      <div className="filter-field">
        <label>From date</label>
        <input type="date" value={dateFrom ?? ""} onChange={(e) => onDateFromChange(e.target.value || undefined)} />
      </div>
      <div className="filter-field">
        <label>To date</label>
        <input type="date" value={dateTo ?? ""} onChange={(e) => onDateToChange(e.target.value || undefined)} />
      </div>
      <button className="filter-reset" onClick={onReset} disabled={!hasActive}>Reset filters</button>
    </aside>
  );
}
