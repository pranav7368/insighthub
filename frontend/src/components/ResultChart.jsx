import {
  Bar, BarChart, CartesianGrid, Cell, Line, LineChart, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { formatNumber } from "../format";

const PIE_COLORS = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--text-muted)"];

function Tip({ active, payload, label, subtype }) {
  if (!active || !payload?.length) return null;
  const p = payload[0];
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip__label">{p.payload.label ?? label}</div>
      <div className="chart-tooltip__value">{formatNumber(p.value, subtype)}</div>
    </div>
  );
}

export default function ResultChart({ result }) {
  const subtype = result.subtype;

  if (result.kind === "scalar") {
    return (
      <div className="result-kpi">
        <div className="result-kpi__value">{formatNumber(result.value, subtype)}</div>
      </div>
    );
  }

  const data = result.data || [];
  if (!data.length) return null;
  const chart = result.chart_type;

  if (chart === "table") {
    return (
      <div className="result-table-wrap">
        <table className="result-table">
          <thead><tr><th>{result.x}</th><th>value</th></tr></thead>
          <tbody>
            {data.map((d, i) => (
              <tr key={i}><td>{d.label}</td><td>{formatNumber(d.value, subtype)}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  if (chart === "line" || result.kind === "series") {
    return (
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={data} margin={{ top: 8, right: 16, left: 8, bottom: 0 }}>
          <CartesianGrid stroke="var(--gridline)" vertical={false} />
          <XAxis dataKey="label" stroke="var(--baseline)" tick={{ fill: "var(--text-muted)", fontSize: 11 }} tickLine={false} minTickGap={20} />
          <YAxis stroke="var(--baseline)" tick={{ fill: "var(--text-muted)", fontSize: 11 }} tickLine={false} axisLine={false}
            tickFormatter={(v) => formatNumber(v, subtype)} width={70} />
          <Tooltip content={<Tip subtype={subtype} />} cursor={{ stroke: "var(--baseline)" }} />
          <Line type="monotone" dataKey="value" stroke="var(--series-1)" strokeWidth={2} dot={{ r: 2.5 }} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    );
  }

  if (chart === "pie") {
    const top = data.slice(0, 3);
    const other = data.slice(3).reduce((s, d) => s + (d.value || 0), 0);
    const slices = [...top];
    if (other > 0) slices.push({ label: "Other", value: other });
    return (
      <ResponsiveContainer width="100%" height={260}>
        <PieChart>
          <Pie data={slices} dataKey="value" nameKey="label" cx="50%" cy="50%" innerRadius={55} outerRadius={90} paddingAngle={2} stroke="var(--surface-1)" strokeWidth={2}>
            {slices.map((_, i) => <Cell key={i} fill={PIE_COLORS[i]} />)}
          </Pie>
          <Tooltip content={<Tip subtype={subtype} />} />
        </PieChart>
      </ResponsiveContainer>
    );
  }

  // default: bar
  return (
    <ResponsiveContainer width="100%" height={Math.max(200, data.length * 34)}>
      <BarChart data={data} layout="vertical" margin={{ top: 8, right: 16, left: 8, bottom: 0 }}>
        <CartesianGrid stroke="var(--gridline)" horizontal={false} />
        <XAxis type="number" stroke="var(--baseline)" tick={{ fill: "var(--text-muted)", fontSize: 11 }}
          tickFormatter={(v) => formatNumber(v, subtype)} tickLine={false} />
        <YAxis type="category" dataKey="label" stroke="var(--baseline)" tick={{ fill: "var(--text-primary)", fontSize: 12 }}
          tickLine={false} axisLine={false} width={110} />
        <Tooltip content={<Tip subtype={subtype} />} cursor={{ fill: "var(--gridline)" }} />
        <Bar dataKey="value" fill="var(--series-1)" radius={[0, 4, 4, 0]} maxBarSize={26} />
      </BarChart>
    </ResponsiveContainer>
  );
}
