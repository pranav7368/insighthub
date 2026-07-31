import { ResponsiveContainer, Tooltip, Treemap } from "recharts";
import { formatNumber, humanLabel } from "../format";

// Fixed palette hexes (SVG fill can't resolve CSS vars reliably); first three
// parents get the validated series hues, the rest a neutral grey.
const PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#898781"];

function Cell(props) {
  const { x, y, width, height, name, depth, fill } = props;
  if (width <= 0 || height <= 0) return null;
  const showLabel = depth === 2 && width > 44 && height > 20;
  return (
    <g>
      <rect x={x} y={y} width={width} height={height} rx={3}
        fill={depth === 2 ? fill || "#898781" : "none"}
        stroke="var(--surface-1)" strokeWidth={2} />
      {showLabel && (
        <text x={x + 6} y={y + 16} fill="#fff" fontSize={11} fontWeight="600"
          style={{ pointerEvents: "none" }}>{name}</text>
      )}
    </g>
  );
}

function TreeTip({ active, payload, subtype }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  if (p.size == null) return null;
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip__label">{p.name}</div>
      <div className="chart-tooltip__value">{formatNumber(p.size, subtype)}</div>
    </div>
  );
}

export default function TreemapChart({ treemap, subtype }) {
  if (!treemap?.root?.length) return null;
  const data = treemap.root.map((p, i) => ({
    name: p.name,
    children: (p.children || []).map((c) => ({ name: c.name, size: c.value, fill: PALETTE[Math.min(i, 3)] })),
  }));

  return (
    <div className="chart-card">
      <div className="chart-card__title">
        {humanLabel(treemap.measure)} by {humanLabel(treemap.parent_dim)} → {humanLabel(treemap.child_dim)}
        <span className="chart-card__tag">box size = value</span>
      </div>
      <ResponsiveContainer width="100%" height={300}>
        <Treemap data={data} dataKey="size" aspectRatio={4 / 3} stroke="var(--surface-1)"
          isAnimationActive={false} content={<Cell />}>
          <Tooltip content={<TreeTip subtype={subtype} />} />
        </Treemap>
      </ResponsiveContainer>
      <div className="donut-legend">
        {treemap.root.slice(0, 4).map((p, i) => (
          <span key={p.name}><i style={{ background: PALETTE[Math.min(i, 3)] }} /> {p.name}</span>
        ))}
      </div>
    </div>
  );
}
