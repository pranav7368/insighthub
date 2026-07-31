import {
  Bar, CartesianGrid, ComposedChart, Line, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { humanLabel } from "../format";

// Single-axis Pareto (no dual axis): each category's share % as bars, the
// cumulative share % as a line, both on one 0–100% scale, with an 80% marker.
function Tip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip__label">{label}</div>
      <div className="chart-tooltip__value">{p.share_pct}% · cumulative {p.cumulative_pct}%</div>
    </div>
  );
}

export default function ParetoChart({ pareto }) {
  if (!pareto?.items?.length) return null;
  const data = pareto.items;
  return (
    <div className="chart-card">
      <div className="chart-card__title">
        Pareto — {humanLabel(pareto.measure)} by {humanLabel(pareto.dimension)}
        {pareto.n_for_80 && <span className="chart-card__tag">top {pareto.n_for_80} of {pareto.total_categories} ≈ 80%</span>}
      </div>
      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart data={data} margin={{ top: 8, right: 16, left: 8, bottom: 30 }}>
          <CartesianGrid stroke="var(--gridline)" vertical={false} />
          <XAxis dataKey="name" stroke="var(--baseline)" tick={{ fill: "var(--text-muted)", fontSize: 11 }}
            tickLine={false} interval={0} angle={-30} textAnchor="end" height={50} />
          <YAxis stroke="var(--baseline)" tick={{ fill: "var(--text-muted)", fontSize: 11 }} tickLine={false}
            axisLine={false} domain={[0, 100]} tickFormatter={(v) => `${v}%`} width={44} />
          <Tooltip content={<Tip />} cursor={{ fill: "var(--gridline)" }} />
          <ReferenceLine y={80} stroke="var(--text-muted)" strokeDasharray="4 4"
            label={{ value: "80%", fill: "var(--text-muted)", fontSize: 10, position: "right" }} />
          <Bar dataKey="share_pct" fill="var(--series-1)" radius={[4, 4, 0, 0]} maxBarSize={44} />
          <Line dataKey="cumulative_pct" stroke="var(--series-2)" strokeWidth={2} dot={{ r: 2 }} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
      <div className="chart-legend">
        <span><i className="lg lg--solid" /> share %</span>
        <span><i className="lg" style={{ background: "var(--series-2)" }} /> cumulative %</span>
        <span><i className="lg lg--dash" /> 80% line</span>
      </div>
    </div>
  );
}
