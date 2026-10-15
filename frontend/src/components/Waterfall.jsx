import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatNumber } from "../format";
import { domainOf, waterfallRows } from "../waterfall";

const COLOR = { total: "var(--text-muted)", up: "var(--series-3)", down: "var(--series-2)" };

function Tip({ active, payload, subtype }) {
  if (!active || !payload?.length) return null;
  const r = payload[0].payload;
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip__label">{r.label}</div>
      <div className="chart-tooltip__value">
        {r.kind === "total" ? formatNumber(r.value, subtype) : `${r.value >= 0 ? "+" : "−"}${formatNumber(Math.abs(r.value), subtype)}`}
      </div>
      {r.step && r.step.clickable && <div className="chart-tooltip__hint">click to drill in</div>}
    </div>
  );
}

// Start total → signed steps → end total; a step marked `clickable` drills in.
export default function Waterfall({ start, steps, end, subtype, onStep, height = 230 }) {
  const rows = waterfallRows(start, steps, end);
  const domain = domainOf(rows);
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={rows} margin={{ top: 8, right: 4, left: 0, bottom: 4 }}
        onClick={(s) => {
          const r = rows[Number(s?.activeIndex ?? s?.activeTooltipIndex)];
          if (r?.step?.clickable && onStep) onStep(r.step);
        }}>
        <CartesianGrid stroke="var(--gridline)" vertical={false} />
        <XAxis dataKey="label" stroke="var(--baseline)" interval={0} tickLine={false} height={46}
          tick={{ fill: "var(--text-muted)", fontSize: 10 }} angle={-25} textAnchor="end" />
        <YAxis stroke="var(--baseline)" tick={{ fill: "var(--text-muted)", fontSize: 10 }} tickLine={false}
          axisLine={false} width={58} domain={domain} allowDataOverflow tickFormatter={(v) => formatNumber(v, subtype)} />
        <Tooltip content={<Tip subtype={subtype} />} cursor={{ fill: "var(--gridline)" }} />
        <Bar dataKey="base" stackId="w" fill="transparent" isAnimationActive={false} />
        <Bar dataKey="bar" stackId="w" radius={[3, 3, 0, 0]} maxBarSize={36} isAnimationActive={false}>
          {rows.map((r, i) => (
            <Cell key={i} fill={COLOR[r.kind]} cursor={r.step?.clickable ? "pointer" : "default"} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
