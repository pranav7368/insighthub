import { useEffect, useState } from "react";
import { errorText, getMetricExplain } from "../api";
import { formatNumber } from "../format";

function formatMetric(value, format) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const n = Number(value);
  if (format === "percent") return `${n.toFixed(1)}%`;
  if (format === "currency") {
    if (Math.abs(n) >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
    if (Math.abs(n) >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`;
    return `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
  }
  return n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

const signedMetric = (v, format) => `${v >= 0 ? "+" : "−"}${formatMetric(Math.abs(v), format)}${format === "percent" ? " pts" : ""}`;

/**
 * The metric tree for one certified metric: its value in the previous and the
 * latest period, and — for a ratio — how much of the move came from the
 * numerator and how much from the denominator. Each part opens in "why it
 * changed", so the tree keeps going down into segments.
 */
function MetricExplain({ metric, onInspect }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let live = true;
    getMetricExplain(metric.metric_id)
      .then((d) => { if (live) setData(d); })
      .catch((e) => { if (live) setError(errorText(e, "Could not explain this metric.")); });
    return () => { live = false; };
  }, [metric.metric_id]);
  if (error) return <p className="metric-tree__err">{error}</p>;
  if (!data) return <div className="skeleton metric-tree__skel" aria-busy="true" aria-label="Loading" />;
  const fmt = (v) => formatMetric(v, metric.format);
  const parts = data.kind === "ratio" ? [["numerator", data.numerator], ["denominator", data.denominator]] : [];
  return (
    <div className="metric-tree">
      <div className="metric-tree__root">
        {data.a.label}: <b>{fmt(data.a.value)}</b> → {data.b.label}: <b>{fmt(data.b.value)}</b>
        {data.delta != null && (
          <span className={`metric-tree__delta delta--${data.delta >= 0 ? "up" : "down"}`}> ({signedMetric(data.delta, metric.format)})</span>
        )}
      </div>
      {parts.map(([role, part]) => (
        <button key={role} className="metric-tree__part" disabled={!part.drill}
          onClick={() => onInspect && onInspect({ ...part.drill, tab: "change", compare: "previous" })}>
          <span className="metric-tree__role">{role}</span>
          <span className="metric-tree__name">{part.agg}({part.column || "rows"})</span>
          <span className="metric-tree__ab">{formatNumber(part.a, part.subtype)} → {formatNumber(part.b, part.subtype)}</span>
          <span className={`metric-tree__effect delta--${part.effect >= 0 ? "up" : "down"}`}>{signedMetric(part.effect, metric.format)}</span>
        </button>
      ))}
      {data.summary && <p className="metric-tree__summary">{data.summary}</p>}
      {data.kind === "aggregate" && data.component?.drill && onInspect && (
        <button className="link-btn" onClick={() => onInspect({ ...data.component.drill, tab: "change", compare: "previous" })}>
          Why did it change? ›
        </button>
      )}
      {data.like_for_like && <p className="metric-tree__note">Like-for-like days: the latest period is incomplete.</p>}
    </div>
  );
}

function MetricCard({ metric, onInspect }) {
  const [showSql, setShowSql] = useState(false);
  const [showTree, setShowTree] = useState(false);
  return (
    <div className="metric-card">
      <div className="metric-card__name">
        {metric.name}
        <span className="metric-card__badge" title="A certified metric — computed the same everywhere">✓ certified</span>
      </div>
      <div className="metric-card__value">
        {metric.error ? <span className="metric-card__err">unavailable</span>
          : formatMetric(metric.value, metric.format)}
      </div>
      <div className="metric-card__actions no-export">
        {metric.sql && (
          <button className="metric-card__sqltoggle" onClick={() => setShowSql((s) => !s)}>
            {showSql ? "Hide SQL" : "Show SQL"}
          </button>
        )}
        {!metric.error && (
          <button className="metric-card__sqltoggle" aria-expanded={showTree} onClick={() => setShowTree((s) => !s)}>
            {showTree ? "Hide change" : "What moved it?"}
          </button>
        )}
      </div>
      {showSql && metric.sql && <pre className="metric-card__sql">{metric.sql}</pre>}
      {showTree && <MetricExplain metric={metric} onInspect={onInspect} />}
    </div>
  );
}

export default function CertifiedMetrics({ metrics, onInspect }) {
  if (!metrics || metrics.length === 0) return null;
  return (
    <div className="metrics-section">
      <div className="section-title">
        Certified metrics <span className="metrics-section__hint">— every number is computed from your data; open “Show SQL” to verify it</span>
      </div>
      <div className="metric-grid">
        {metrics.map((m) => <MetricCard key={m.metric_id} metric={m} onInspect={onInspect} />)}
      </div>
    </div>
  );
}
