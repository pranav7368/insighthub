import {
  CartesianGrid, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart as RScatter,
  Tooltip, XAxis, YAxis,
} from "recharts";
import { formatNumber, humanLabel } from "../format";

function strength(r) {
  if (r == null) return "not enough data";
  const a = Math.abs(r);
  const dir = r > 0 ? "positive" : "negative";
  const mag = a >= 0.7 ? "strong" : a >= 0.4 ? "moderate" : "weak";
  return `${mag} ${dir} (r = ${r.toFixed(2)})`;
}

function Tip({ active, payload, sx, sy }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip__label">{formatNumber(p.x, sx)}</div>
      <div className="chart-tooltip__value">{formatNumber(p.y, sy)}</div>
    </div>
  );
}

export default function ScatterPlot({ scatter }) {
  if (!scatter?.points?.length) {
    return <div className="empty-panel">Not enough numeric data to plot a relationship.</div>;
  }
  const { x, y, points, line, r, subtype_x: sx, subtype_y: sy } = scatter;
  return (
    <div className="chart-card">
      <div className="chart-card__title">
        {humanLabel(x)} vs {humanLabel(y)}
        <span className="chart-card__tag">{strength(r)}</span>
      </div>
      <ResponsiveContainer width="100%" height={280}>
        <RScatter margin={{ top: 10, right: 18, left: 8, bottom: 8 }}>
          <CartesianGrid stroke="var(--gridline)" />
          <XAxis type="number" dataKey="x" name={x} stroke="var(--baseline)"
            tick={{ fill: "var(--text-muted)", fontSize: 11 }} tickLine={false}
            tickFormatter={(v) => formatNumber(v, sx)} />
          <YAxis type="number" dataKey="y" name={y} stroke="var(--baseline)"
            tick={{ fill: "var(--text-muted)", fontSize: 11 }} tickLine={false} axisLine={false}
            tickFormatter={(v) => formatNumber(v, sy)} width={70} />
          <Tooltip content={<Tip sx={sx} sy={sy} />} cursor={{ strokeDasharray: "3 3" }} />
          {line && (
            <ReferenceLine ifOverflow="extendDomain" stroke="var(--series-2)" strokeWidth={2}
              segment={[{ x: line[0].x, y: line[0].y }, { x: line[1].x, y: line[1].y }]} />
          )}
          <Scatter data={points} fill="var(--series-1)" fillOpacity={0.55} />
        </RScatter>
      </ResponsiveContainer>
    </div>
  );
}
