import { formatNumber, humanLabel } from "../format";

export default function StatTile({ kpi, active, onSelect }) {
  return (
    <button className={`stat-tile ${active ? "stat-tile--active" : ""}`} onClick={onSelect}>
      <div className="stat-tile__label">{humanLabel(kpi.column)}</div>
      <div className="stat-tile__value">{formatNumber(kpi.total, kpi.subtype)}</div>
      <div className="stat-tile__sub">avg {formatNumber(kpi.average, kpi.subtype)} / row</div>
    </button>
  );
}
