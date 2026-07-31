import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { formatNumber, humanLabel } from "../format";

function ChartTooltip({ active, payload, label, subtype }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip__label">{label}</div>
      <div className="chart-tooltip__value">{formatNumber(payload[0].value, subtype)}</div>
    </div>
  );
}

export default function TrendChart({ data, measure, subtype }) {
  if (!data?.length) {
    return <div className="empty-panel">No time trend for this measure (a date column is required).</div>;
  }
  return (
    <div className="chart-card">
      <div className="chart-card__title">{humanLabel(measure)} over time</div>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={data} margin={{ top: 8, right: 16, left: 8, bottom: 0 }}>
          <CartesianGrid stroke="var(--gridline)" vertical={false} />
          <XAxis dataKey="period" stroke="var(--baseline)" tick={{ fill: "var(--text-muted)", fontSize: 12 }} tickLine={false} />
          <YAxis stroke="var(--baseline)" tick={{ fill: "var(--text-muted)", fontSize: 12 }} tickLine={false}
            axisLine={false} tickFormatter={(v) => formatNumber(v, subtype)} width={72} />
          <Tooltip content={<ChartTooltip subtype={subtype} />} cursor={{ stroke: "var(--baseline)" }} />
          <Line type="monotone" dataKey={measure} stroke="var(--series-1)" strokeWidth={2}
            dot={{ r: 3, fill: "var(--series-1)" }} activeDot={{ r: 5 }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
