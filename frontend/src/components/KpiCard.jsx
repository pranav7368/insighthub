import { formatNumber, humanLabel } from "../format";
import { TARGET_STATUS, isMenuKey } from "../drill";
import Sparkline from "./Sparkline";

function TargetLine({ target, subtype }) {
  if (!target || target.status === "broken") return null;
  const pct = Math.round(((target.status === "met" ? target.progress : target.projected_ratio) || 0) * 100);
  return (
    <span className={`kpi-card__target target--${target.status}`}
      title={`${target.period} target ${formatNumber(target.value, subtype)}: ${TARGET_STATUS[target.status]}`}>
      <span className="kpi-card__target-bar" aria-hidden>
        <span style={{ width: `${Math.min(100, (target.progress || 0) * 100)}%` }} />
      </span>
      {TARGET_STATUS[target.status]} · {target.status === "met" ? `${pct}% of` : `pace ${pct}% of`} {formatNumber(target.value, subtype)}
    </span>
  );
}

export default function KpiCard({ kpi, active, onSelect, onContext, target }) {
  const delta = kpi.delta_pct;
  const hasDelta = delta !== null && delta !== undefined;
  const up = hasDelta && delta > 0;
  const flat = hasDelta && delta === 0;
  const deltaClass = flat ? "flat" : up ? "up" : "down";

  return (
    <button className={`kpi-card ${active ? "kpi-card--active" : ""}`} onClick={onSelect}
      onContextMenu={onContext ? (e) => { e.preventDefault(); onContext(e); } : undefined}
      onKeyDown={onContext ? (e) => { if (isMenuKey(e)) { e.preventDefault(); onContext(e); } } : undefined}>
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
      <TargetLine target={target} subtype={kpi.subtype} />
    </button>
  );
}
