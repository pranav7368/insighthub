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
          {/* htmlFor/id, not just proximity: a <label> that names no control
              is invisible to a screen reader, which then announces this as an
              unlabelled combo box */}
          <label htmlFor={`filter-${name}`}>{humanLabel(name)}</label>
          <select
            id={`filter-${name}`}
            value={activeFilters[name] ?? ""}
            onChange={(e) => onFilterChange(name, e.target.value || undefined)}
          >
            <option value="">All</option>
            {meta.values.map((v) => <option key={v} value={v}>{v}</option>)}
          </select>
        </div>
      ))}
      <div className="filter-field">
        <label htmlFor="filter-date-from">From date</label>
        <input id="filter-date-from" type="date" value={dateFrom ?? ""}
          onChange={(e) => onDateFromChange(e.target.value || undefined)} />
      </div>
      <div className="filter-field">
        <label htmlFor="filter-date-to">To date</label>
        <input id="filter-date-to" type="date" value={dateTo ?? ""}
          onChange={(e) => onDateToChange(e.target.value || undefined)} />
      </div>
      <button className="filter-reset" onClick={onReset} disabled={!hasActive}>Reset filters</button>
    </aside>
  );
}
