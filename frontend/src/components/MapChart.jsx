import { useState } from "react";
import indiaGeo from "../assets/india.geo.json";
import { INDIA_BBOX, coordFor, makeProjection } from "../geo";
import { formatNumber, humanLabel } from "../format";

const W = 380, H = 430;
const project = makeProjection(INDIA_BBOX, W, H);

// Build SVG path strings for the country outline (Polygon or MultiPolygon).
function outlinePaths() {
  const feat = indiaGeo.features?.[0];
  if (!feat) return [];
  const geom = feat.geometry;
  const polys = geom.type === "MultiPolygon" ? geom.coordinates : [geom.coordinates];
  return polys.map((rings) =>
    rings.map((ring) => {
      const pts = ring.map((c) => project(c));
      return "M" + pts.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("L") + "Z";
    }).join(" ")
  );
}
const PATHS = outlinePaths();

export default function MapChart({ dimensionName, breakdown, measure, subtype }) {
  const [hover, setHover] = useState(null);
  const data = (breakdown?.data || []).filter((d) => coordFor(d.name));
  if (data.length < 2) return null;

  const maxV = Math.max(...data.map((d) => d.value || 0)) || 1;
  const radius = (v) => 5 + 20 * Math.sqrt(Math.max(v, 0) / maxV);
  // draw largest bubbles first so small ones stay clickable on top
  const points = [...data].sort((a, b) => (b.value || 0) - (a.value || 0));

  return (
    <div className="chart-card">
      <div className="chart-card__title">
        {humanLabel(measure)} by {humanLabel(dimensionName)} — map
        <span className="chart-card__tag">bubble size = value</span>
      </div>
      <div className="map-wrap">
        <svg viewBox={`0 0 ${W} ${H}`} className="map-svg" role="img" aria-label="Geographic distribution">
          {PATHS.map((d, i) => (
            <path key={i} d={d} fill="var(--surface-2)" stroke="var(--baseline)" strokeWidth={0.8} />
          ))}
          {points.map((d) => {
            const [x, y] = project(coordFor(d.name));
            const r = radius(d.value || 0);
            const active = hover?.name === d.name;
            return (
              <g key={d.name} onMouseEnter={() => setHover({ name: d.name, value: d.value, x, y })}
                onMouseLeave={() => setHover(null)} style={{ cursor: "default" }}>
                <circle cx={x} cy={y} r={r} fill="var(--series-1)" fillOpacity={active ? 0.85 : 0.55}
                  stroke="var(--surface-1)" strokeWidth={1.5} />
                {r > 13 && (
                  <text x={x} y={y + 3} textAnchor="middle" fontSize={10} fontWeight="600"
                    fill="#fff" style={{ pointerEvents: "none" }}>{d.name}</text>
                )}
              </g>
            );
          })}
          {hover && (
            <g style={{ pointerEvents: "none" }}>
              <rect x={Math.min(hover.x + 8, W - 120)} y={Math.max(hover.y - 30, 2)} width={118} height={30} rx={5}
                fill="var(--surface-1)" stroke="var(--border)" />
              <text x={Math.min(hover.x + 14, W - 114)} y={Math.max(hover.y - 17, 15)} fontSize={10} fill="var(--text-muted)">{hover.name}</text>
              <text x={Math.min(hover.x + 14, W - 114)} y={Math.max(hover.y - 5, 27)} fontSize={11} fontWeight="600" fill="var(--text-primary)">
                {formatNumber(hover.value, subtype)}
              </text>
            </g>
          )}
        </svg>
      </div>
    </div>
  );
}
