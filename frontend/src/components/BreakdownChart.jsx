import { useRef } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatNumber, humanLabel } from "../format";

function ChartTooltip({ active, payload, subtype, total }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip__label">{p.name} · #{p.rank} of {total}</div>
      <div className="chart-tooltip__value">
        {formatNumber(p.value, subtype)}{p.share_pct != null ? ` · ${p.share_pct}% of the total` : ""}
      </div>
      <div className="chart-tooltip__hint">click for details · right-click for more</div>
    </div>
  );
}

export default function BreakdownChart({ dimensionName, breakdown, measure, subtype, onSelect, onShowAll, onContext, activeValue }) {
  const hovered = useRef(null);
  const data = (breakdown?.data ?? []).map((d, i) => ({ ...d, rank: i + 1 }));
  const total = data.length + (breakdown?.others?.count || 0);
  if (!data.length) return <div className="empty-panel">No data for {humanLabel(dimensionName)}.</div>;

  const barColor = (name) =>
    !activeValue ? "var(--series-1)" : name === activeValue ? "var(--series-1)" : "var(--gridline)";

  return (
    <div className="chart-card" onContextMenu={(e) => {
      if (!onContext || hovered.current == null) return;
      e.preventDefault();
      onContext(e, dimensionName, hovered.current);
    }}>
      <div className="chart-card__title">
        {humanLabel(measure)} by {humanLabel(dimensionName)}
        <span className="chart-card__tag chart-card__hint">click a bar for details</span>
      </div>
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={data} layout="vertical" margin={{ top: 8, right: 16, left: 8, bottom: 0 }}
          onMouseLeave={() => { hovered.current = null; }}>
          <CartesianGrid stroke="var(--gridline)" horizontal={false} />
          <XAxis type="number" stroke="var(--baseline)" tick={{ fill: "var(--text-muted)", fontSize: 12 }}
            tickFormatter={(v) => formatNumber(v, subtype)} tickLine={false} />
          <YAxis type="category" dataKey="name" stroke="var(--baseline)"
            tick={{ fill: "var(--text-primary)", fontSize: 12 }} tickLine={false} axisLine={false} width={110} />
          <Tooltip content={<ChartTooltip subtype={subtype} total={total} />} cursor={{ fill: "var(--gridline)" }} />
          <Bar dataKey="value" radius={[0, 4, 4, 0]} maxBarSize={26} cursor="pointer"
            onMouseEnter={(bar) => { hovered.current = bar?.payload?.name ?? bar?.name ?? null; }}
            onClick={(bar) => onSelect && onSelect(dimensionName, bar?.payload?.name ?? bar?.name)}>
            {data.map((d, i) => <Cell key={i} fill={barColor(d.name)} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      {breakdown.others && (
        <button className="chart-card__more no-export" onClick={() => onShowAll && onShowAll(dimensionName)}>
          + {breakdown.others.count} more {humanLabel(dimensionName).toLowerCase()} values
          ({formatNumber(breakdown.others.value, subtype)}, {breakdown.others.share_pct}%) — see all ›
        </button>
      )}
    </div>
  );
}
