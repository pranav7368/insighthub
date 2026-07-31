import { humanLabel } from "../format";

// Diverging encoding: positive correlation -> blue, negative -> red, ~0 ->
// neutral surface. Magnitude drives colour intensity. Click a cell to load
// that pair as a scatter plot.
function cellStyle(v) {
  if (v == null) return { background: "var(--surface-2)", color: "var(--text-muted)" };
  const pct = Math.round(Math.abs(v) * 100);
  const hue = v >= 0 ? "var(--series-1)" : "var(--status-critical)";
  return {
    background: `color-mix(in srgb, ${hue} ${pct}%, var(--surface-1))`,
    color: pct > 55 ? "#fff" : "var(--text-primary)",
  };
}

export default function CorrelationHeatmap({ correlations, activePair, onSelect }) {
  const { measures, matrix } = correlations;
  return (
    <div className="chart-card">
      <div className="chart-card__title">
        Correlation matrix
        <span className="chart-card__tag">click a cell to plot the pair</span>
      </div>
      <div className="heatmap-scroll">
        <table className="heatmap">
          <thead>
            <tr>
              <th />
              {measures.map((m) => <th key={m} className="heatmap__colh">{humanLabel(m)}</th>)}
            </tr>
          </thead>
          <tbody>
            {measures.map((rowM, i) => (
              <tr key={rowM}>
                <th className="heatmap__rowh">{humanLabel(rowM)}</th>
                {measures.map((colM, j) => {
                  const v = matrix[i][j];
                  const selectable = i !== j && v != null;
                  const isActive = activePair && ((activePair.x === rowM && activePair.y === colM) || (activePair.x === colM && activePair.y === rowM));
                  return (
                    <td key={colM}
                      className={`heatmap__cell ${selectable ? "heatmap__cell--click" : ""} ${isActive ? "heatmap__cell--active" : ""}`}
                      style={cellStyle(v)}
                      onClick={() => selectable && onSelect(rowM, colM)}
                      title={`${humanLabel(rowM)} vs ${humanLabel(colM)}: r = ${v}`}>
                      {v == null ? "—" : v.toFixed(2)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
