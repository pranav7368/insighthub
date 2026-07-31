import { useState } from "react";
import { formatNumber, humanLabel } from "../format";

function DriverBar({ d, max, subtype }) {
  const pos = d.delta >= 0;
  const width = max > 0 ? Math.max(2, (Math.abs(d.delta) / max) * 100) : 0;
  return (
    <div className="driver-row">
      <div className="driver-row__name">{d.name}</div>
      <div className="driver-row__track">
        <div className={`driver-row__bar driver-row__bar--${pos ? "up" : "down"}`} style={{ width: `${width}%` }} />
      </div>
      <div className={`driver-row__delta driver-row__delta--${pos ? "up" : "down"}`}>
        {pos ? "+" : "−"}{formatNumber(Math.abs(d.delta), subtype)}
        {d.share != null && <span className="driver-row__share">{Math.round(Math.abs(d.share) * 100)}%</span>}
      </div>
    </div>
  );
}

export default function DriverAnalysis({ explain }) {
  const dims = explain?.dimensions ? Object.keys(explain.dimensions) : [];
  const [dim, setDim] = useState(explain?.primary_dimension || dims[0] || null);

  if (!explain?.available || !dim) return null;
  const active = dim in explain.dimensions ? dim : explain.primary_dimension;
  const drivers = explain.dimensions[active]?.drivers || [];
  const max = Math.max(0, ...drivers.map((d) => Math.abs(d.delta)));
  const up = explain.delta > 0;

  return (
    <div className="driver-section card">
      <div className="driver-head">
        <div className="section-title" style={{ margin: 0 }}>What changed</div>
        {dims.length > 1 && (
          <select className="driver-dimselect" value={active} onChange={(e) => setDim(e.target.value)}>
            {dims.map((d) => <option key={d} value={d}>by {humanLabel(d)}</option>)}
          </select>
        )}
      </div>

      <div className="driver-headline">
        <span className={`driver-chip driver-chip--${up ? "up" : "down"}`}>
          {up ? "▲" : "▼"} {explain.pct_change == null ? "" : `${Math.abs(explain.pct_change).toFixed(1)}%`}
        </span>
        <span className="driver-summary">{explain.summary}</span>
      </div>

      <div className="driver-bars">
        {drivers.map((d) => <DriverBar key={d.name} d={d} max={max} subtype={explain.subtype} />)}
      </div>
    </div>
  );
}
