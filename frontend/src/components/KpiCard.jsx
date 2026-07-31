import { formatNumber, humanLabel } from "../format";
import Sparkline from "./Sparkline";

export default function KpiCard({ kpi, active, onSelect }) {
  const delta = kpi.delta_pct;
  const hasDelta = delta !== null && delta !== undefined;
  const up = hasDelta && delta > 0;
  const flat = hasDelta && delta === 0;
  const deltaClass = flat ? "flat" : up ? "up" : "down";

  return (
    <button className={`kpi-card ${active ? "kpi-card--active" : ""}`} onClick={onSelect}>
      <div className="kpi-card__top">
        <span className="kpi-card__label">{humanLabel(kpi.column)}</span>
        {hasDelta && (
          <span className={`kpi-card__delta kpi-card__delta--${deltaClass}`}>
            {up ? "▲" : flat ? "▬" : "▼"} {Math.abs(delta)}%
          </span>
        )}
      </div>
      <div className="kpi-card__value">{formatNumber(kpi.total, kpi.subtype)}</div>
      <div className="kpi-card__foot">
        <span className="kpi-card__sub">
          {kpi.period_label ? `${formatNumber(kpi.current_period, kpi.subtype)} in ${kpi.period_label}` : `avg ${formatNumber(kpi.average, kpi.subtype)}`}
        </span>
        <Sparkline values={kpi.sparkline} color={active ? "var(--series-1)" : "var(--text-muted)"} />
      </div>
    </button>
  );
}
