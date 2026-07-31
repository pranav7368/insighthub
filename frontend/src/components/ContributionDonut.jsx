import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { formatNumber, humanLabel } from "../format";

// Palette-safe: top 3 segments get the three validated series hues, the rest
// fold into a neutral "Other" slice (never cycle beyond the validated set).
const COLORS = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--text-muted)"];

export default function ContributionDonut({ dimensionName, breakdown, subtype, onSelect, activeValue }) {
  const raw = breakdown?.data ?? [];
  if (raw.length < 2) return null;
  const top = raw.slice(0, 3);
  const otherValue = raw.slice(3).reduce((s, d) => s + (d.value || 0), 0);
  const otherShare = raw.slice(3).reduce((s, d) => s + (d.share_pct || 0), 0);
  const data = [...top.map((d) => ({ name: d.name, value: d.value, share: d.share_pct }))];
  if (otherValue > 0) data.push({ name: "Other", value: otherValue, share: Math.round(otherShare * 10) / 10 });

  const sliceColor = (name, i) => {
    if (activeValue && name !== activeValue) return "var(--gridline)";
    return COLORS[i];
  };

  return (
    <div className="chart-card">
      <div className="chart-card__title">
        Contribution by {humanLabel(dimensionName)}
        <span className="chart-card__tag">click a slice to filter</span>
      </div>
      <ResponsiveContainer width="100%" height={240}>
        <PieChart>
          <Pie data={data} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={55} outerRadius={90}
            paddingAngle={2} stroke="var(--surface-1)" strokeWidth={2} cursor="pointer"
            onClick={(slice) => onSelect && slice?.name && slice.name !== "Other" && onSelect(dimensionName, slice.name)}>
            {data.map((d, i) => <Cell key={i} fill={sliceColor(d.name, i)} />)}
          </Pie>
          <Tooltip content={({ active, payload }) =>
            active && payload?.length ? (
              <div className="chart-tooltip">
                <div className="chart-tooltip__label">{payload[0].name}</div>
                <div className="chart-tooltip__value">{formatNumber(payload[0].value, subtype)} · {payload[0].payload.share}%</div>
              </div>
            ) : null
          } />
        </PieChart>
      </ResponsiveContainer>
      <div className="donut-legend">
        {data.map((d, i) => (
          <span key={d.name}><i style={{ background: COLORS[i] }} /> {d.name} <b>{d.share}%</b></span>
        ))}
      </div>
    </div>
  );
}
