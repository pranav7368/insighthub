import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { formatNumber, humanLabel } from "../format";

// Overlays two series (A vs B) on a shared time axis. Two series => a legend
// is always shown, so identity is never colour-alone.
function Tip({ active, payload, label, subtype, labelA, labelB }) {
  if (!active || !payload?.length) return null;
  const a = payload.find((p) => p.dataKey === "a");
  const b = payload.find((p) => p.dataKey === "b");
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip__label">{label}</div>
      {a && <div className="chart-tooltip__value" style={{ color: "var(--series-1)" }}>{labelA}: {formatNumber(a.value, subtype)}</div>}
      {b && <div className="chart-tooltip__value" style={{ color: "var(--series-2)" }}>{labelB}: {formatNumber(b.value, subtype)}</div>}
    </div>
  );
}

export default function ComparisonChart({ data, measure, subtype, labelA, labelB }) {
  if (!data?.length) return null;
  return (
    <div className="chart-card">
      <div className="chart-card__title">{humanLabel(measure)} over time — {labelA} vs {labelB}</div>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={data} margin={{ top: 8, right: 16, left: 8, bottom: 0 }}>
          <CartesianGrid stroke="var(--gridline)" vertical={false} />
          <XAxis dataKey="period" stroke="var(--baseline)" tick={{ fill: "var(--text-muted)", fontSize: 11 }} tickLine={false} minTickGap={20} />
          <YAxis stroke="var(--baseline)" tick={{ fill: "var(--text-muted)", fontSize: 11 }} tickLine={false} axisLine={false}
            tickFormatter={(v) => formatNumber(v, subtype)} width={70} />
          <Tooltip content={<Tip subtype={subtype} labelA={labelA} labelB={labelB} />} cursor={{ stroke: "var(--baseline)" }} />
          <Line dataKey="a" name={labelA} stroke="var(--series-1)" strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />
          <Line dataKey="b" name={labelB} stroke="var(--series-2)" strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />
        </LineChart>
      </ResponsiveContainer>
      <div className="chart-legend">
        <span><i className="lg" style={{ background: "var(--series-1)" }} /> {labelA}</span>
        <span><i className="lg" style={{ background: "var(--series-2)" }} /> {labelB}</span>
      </div>
    </div>
  );
}
