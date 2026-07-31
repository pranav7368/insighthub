import {
  Area, CartesianGrid, ComposedChart, Line, ReferenceDot,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { formatNumber, humanLabel } from "../format";

function ChartTooltip({ active, payload, label, subtype }) {
  if (!active || !payload?.length) return null;
  const actual = payload.find((p) => p.dataKey === "actual" && p.value != null);
  const projected = payload.find((p) => p.dataKey === "projected" && p.value != null);
  const row = actual || projected;
  if (!row) return null;
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip__label">{label}{projected && !actual ? " · projected" : ""}</div>
      <div className="chart-tooltip__value">{formatNumber(row.value, subtype)}</div>
    </div>
  );
}

export default function ForecastChart({ measure, subtype, forecast, anomalies }) {
  if (!forecast?.history?.length) {
    return <div className="empty-panel">No time series for this measure (a date column is required).</div>;
  }
  const history = forecast.history;
  const proj = forecast.forecast || [];
  const ma = forecast.moving_avg || [];

  const data = [
    ...history.map((h, i) => ({ period: h.period, actual: h.value, ma: ma[i] ?? null })),
    ...proj.map((f) => ({ period: f.period, projected: f.value, band: [f.lower, f.upper] })),
  ];
  // bridge the projection line to the last real point
  if (proj.length && data[history.length - 1]) {
    data[history.length - 1].projected = data[history.length - 1].actual;
  }
  const anomalyByPeriod = Object.fromEntries((anomalies || []).map((a) => [a.period, a]));

  return (
    <div className="chart-card">
      <div className="chart-card__title">
        {humanLabel(measure)} — trend & forecast
        {proj.length > 0 && <span className="chart-card__tag">next {proj.length}mo · {forecast.method.replace("+", " + ")}</span>}
      </div>
      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart data={data} margin={{ top: 8, right: 16, left: 8, bottom: 0 }}>
          <CartesianGrid stroke="var(--gridline)" vertical={false} />
          <XAxis dataKey="period" stroke="var(--baseline)" tick={{ fill: "var(--text-muted)", fontSize: 11 }} tickLine={false} minTickGap={20} />
          <YAxis stroke="var(--baseline)" tick={{ fill: "var(--text-muted)", fontSize: 11 }} tickLine={false} axisLine={false}
            tickFormatter={(v) => formatNumber(v, subtype)} width={72} />
          <Tooltip content={<ChartTooltip subtype={subtype} />} cursor={{ stroke: "var(--baseline)" }} />
          <Area dataKey="band" stroke="none" fill="var(--series-1)" fillOpacity={0.12} isAnimationActive={false} connectNulls />
          <Line dataKey="ma" stroke="var(--text-muted)" strokeWidth={1.5} strokeDasharray="2 2" dot={false} isAnimationActive={false} connectNulls />
          <Line dataKey="actual" stroke="var(--series-1)" strokeWidth={2} dot={false} isAnimationActive={false} connectNulls={false} />
          <Line dataKey="projected" stroke="var(--series-1)" strokeWidth={2} strokeDasharray="5 4" dot={false} isAnimationActive={false} connectNulls />
          {history.map((h) =>
            anomalyByPeriod[h.period] ? (
              <ReferenceDot key={h.period} x={h.period} y={h.value} r={5}
                fill="var(--status-critical)" stroke="var(--surface-1)" strokeWidth={2} isFront />
            ) : null
          )}
        </ComposedChart>
      </ResponsiveContainer>
      <div className="chart-legend">
        <span><i className="lg lg--solid" /> Actual</span>
        <span><i className="lg lg--dash" /> Forecast</span>
        <span><i className="lg lg--band" />95% range</span>
        <span><i className="lg lg--madash" /> 3-mo avg</span>
        {(anomalies || []).length > 0 && <span><i className="lg lg--dot" /> Anomaly</span>}
      </div>
    </div>
  );
}
