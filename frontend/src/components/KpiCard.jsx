import { formatDate, formatNumber, humanLabel } from "../format";
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

function Change({ label, v }) {
  if (v == null) return null;
  const dir = v > 0 ? "up" : v < 0 ? "down" : "flat";
  return (
    <span className={`kpi-chg kpi-chg--${dir}`} title={`${label}: ${v > 0 ? "+" : ""}${v}%`}>
      <span className="kpi-chg__label">{label}</span> {dir === "up" ? "▲" : dir === "down" ? "▼" : "▬"}{Math.abs(v)}%
    </span>
  );
}

/**
 * One number, once: its total, how the latest month moved, longer-run growth,
 * a sparkline, its target pace — and a "certified" mark when a certified metric
 * defines exactly this total, so the same figure is not shown twice.
 */
export default function KpiCard({ kpi, active, onSelect, onContext, target, growth, certified }) {
  const delta = kpi.delta_pct;
  const hasDelta = delta !== null && delta !== undefined;
  const dir = !hasDelta ? null : delta > 0 ? "up" : delta < 0 ? "down" : "flat";

  return (
    <button className={`kpi-card ${active ? "kpi-card--active" : ""}`} onClick={onSelect}
      aria-pressed={active}
      onContextMenu={onContext ? (e) => { e.preventDefault(); onContext(e); } : undefined}
      onKeyDown={onContext ? (e) => { if (isMenuKey(e)) { e.preventDefault(); onContext(e); } } : undefined}>
      <div className="kpi-card__top">
        <span className="kpi-card__label">{humanLabel(kpi.column)}</span>
        {certified && (
          <span className="kpi-card__cert" title={`Certified metric “${certified}” — computed the same everywhere`}>
            ✓ certified
          </span>
        )}
      </div>
      <div className="kpi-card__value">{formatNumber(kpi.total, kpi.subtype)}</div>
      <div className="kpi-card__mid">
        {hasDelta && (
          <span className={`kpi-card__delta kpi-card__delta--${dir}`}>
            {dir === "up" ? "▲" : dir === "down" ? "▼" : "▬"} {Math.abs(delta)}%
            <span className="kpi-card__delta-label"> vs previous month</span>
          </span>
        )}
        <Sparkline values={kpi.sparkline} color={active ? "var(--series-1)" : "var(--text-muted)"} />
      </div>
      <div className="kpi-card__foot">
        <span className="kpi-card__sub">
          {kpi.period_label
            ? `${formatNumber(kpi.current_period, kpi.subtype)} in ${formatDate(kpi.period_label)}`
            : `avg ${formatNumber(kpi.average, kpi.subtype)}`}
        </span>
        {growth && (growth.qoq != null || growth.yoy != null) && (
          <span className="kpi-card__growth">
            <Change label="QoQ" v={growth.qoq} />
            <Change label="YoY" v={growth.yoy} />
          </span>
        )}
      </div>
      <TargetLine target={target} subtype={kpi.subtype} />
    </button>
  );
}
