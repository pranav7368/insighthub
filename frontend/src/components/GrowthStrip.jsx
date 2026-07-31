import { humanLabel } from "../format";

function Item({ label, v }) {
  if (v == null) return null;
  const up = v > 0, flat = v === 0;
  return (
    <div className="growth-item">
      <span className="growth-item__label">{label}</span>
      <span className={`growth-item__val ${flat ? "flat" : up ? "up" : "down"}`}>
        {up ? "▲" : flat ? "▬" : "▼"} {Math.abs(v)}%
      </span>
    </div>
  );
}

export default function GrowthStrip({ growth, measure }) {
  const g = growth?.[measure];
  if (!g) return null;
  const hasAny = g.mom != null || g.qoq != null || g.yoy != null;
  if (!hasAny) return null;
  return (
    <div className="growth-strip">
      <span className="growth-strip__title">{humanLabel(measure)} growth</span>
      <Item label="MoM" v={g.mom} />
      <Item label="QoQ" v={g.qoq} />
      <Item label="YoY" v={g.yoy} />
    </div>
  );
}
