import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatNumber, humanLabel } from "../format";

function ChartTooltip({ active, payload, subtype }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip__label">{p.name}</div>
      <div className="chart-tooltip__value">
        {formatNumber(p.value, subtype)}{p.share_pct != null ? ` · ${p.share_pct}%` : ""}
      </div>
    </div>
  );
}

export default function BreakdownChart({ dimensionName, breakdown, measure, subtype, onSelect, activeValue }) {
  const data = breakdown?.data ?? [];
  if (!data.length) return <div className="empty-panel">No data for {humanLabel(dimensionName)}.</div>;

  const barColor = (name) =>
    !activeValue ? "var(--series-1)" : name === activeValue ? "var(--series-1)" : "var(--gridline)";

  return (
    <div className="chart-card">
      <div className="chart-card__title">
        {humanLabel(measure)} by {humanLabel(dimensionName)}
        <span className="chart-card__tag">click a bar to filter</span>
      </div>
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={data} layout="vertical" margin={{ top: 8, right: 16, left: 8, bottom: 0 }}>
          <CartesianGrid stroke="var(--gridline)" horizontal={false} />
          <XAxis type="number" stroke="var(--baseline)" tick={{ fill: "var(--text-muted)", fontSize: 12 }}
            tickFormatter={(v) => formatNumber(v, subtype)} tickLine={false} />
          <YAxis type="category" dataKey="name" stroke="var(--baseline)"
            tick={{ fill: "var(--text-primary)", fontSize: 12 }} tickLine={false} axisLine={false} width={110} />
          <Tooltip content={<ChartTooltip subtype={subtype} />} cursor={{ fill: "var(--gridline)" }} />
          <Bar dataKey="value" radius={[0, 4, 4, 0]} maxBarSize={26} cursor="pointer"
            onClick={(bar) => onSelect && onSelect(dimensionName, bar?.payload?.name ?? bar?.name)}>
            {data.map((d, i) => <Cell key={i} fill={barColor(d.name)} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
