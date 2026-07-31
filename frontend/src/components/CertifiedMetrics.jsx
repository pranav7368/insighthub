import { useState } from "react";

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

function MetricCard({ metric }) {
  const [showSql, setShowSql] = useState(false);
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
      {metric.sql && (
        <button className="metric-card__sqltoggle no-export" onClick={() => setShowSql((s) => !s)}>
          {showSql ? "Hide SQL" : "Show SQL"}
        </button>
      )}
      {showSql && metric.sql && <pre className="metric-card__sql">{metric.sql}</pre>}
    </div>
  );
}

export default function CertifiedMetrics({ metrics }) {
  if (!metrics || metrics.length === 0) return null;
  return (
    <div className="metrics-section">
      <div className="section-title">
        Certified metrics <span className="metrics-section__hint">— every number is computed from your data; open “Show SQL” to verify it</span>
      </div>
      <div className="metric-grid">
        {metrics.map((m) => <MetricCard key={m.metric_id} metric={m} />)}
      </div>
    </div>
  );
}
