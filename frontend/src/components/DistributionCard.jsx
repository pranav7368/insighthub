import { formatNumber, humanLabel } from "../format";

// Compact box-plot: track from min→max, box from q1→q3, median tick.
export default function DistributionCard({ name, dist }) {
  const { min, q1, median, q3, max, std, subtype } = dist;
  const span = max - min || 1;
  const pct = (v) => ((v - min) / span) * 100;

  return (
    <div className="dist-card">
      <div className="dist-card__name">{humanLabel(name)}</div>
      <div className="dist-track">
        <div className="dist-box" style={{ left: `${pct(q1)}%`, width: `${pct(q3) - pct(q1)}%` }} />
        <div className="dist-median" style={{ left: `${pct(median)}%` }} />
      </div>
      <div className="dist-scale">
        <span>{formatNumber(min, subtype)}</span>
        <span className="dist-scale__mid">med {formatNumber(median, subtype)}</span>
        <span>{formatNumber(max, subtype)}</span>
      </div>
      {std != null && <div className="dist-std">σ {formatNumber(std, subtype)}</div>}
    </div>
  );
}
