import { useEffect, useState } from "react";
import { getVariance } from "../api";
import { TARGET_STATUS, pctText } from "../drill";
import { formatNumber, humanLabel } from "../format";
import Icon from "./Icon";

const SEV_LABEL = { high: "Act now", medium: "Worth a look", low: "Opportunity" };

/**
 * The first thing on the dashboard: what happened, whether it is unusual,
 * where the target stands, and what to do about it — each one click from
 * the evidence. Everything in it is computed; nothing is generated.
 */
export default function SummaryCard({ datasetId, measure, subtype, filters, dateFrom, dateTo, target,
  actions, onOpen, onSeeActions }) {
  const [change, setChange] = useState(null);
  const key = JSON.stringify([datasetId, measure, filters, dateFrom, dateTo]);

  useEffect(() => {
    let live = true;
    setChange(null);
    getVariance(datasetId, { measure, filters, date_from: dateFrom || null, date_to: dateTo || null })
      .then((d) => { if (live) setChange(d); })
      .catch(() => { if (live) setChange(false); });     // no date column etc.: just leave it out
    return () => { live = false; };
    // inputs are captured through key
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const top = (actions || []).slice(0, 2);
  if (change === false && !target && top.length === 0) return null;
  const sig = change?.significance;
  const dir = change ? (change.delta > 0 ? "up" : change.delta < 0 ? "down" : "flat") : null;

  return (
    <section className="summary" aria-label="Summary">
      <div className="summary__main">
        <div className="summary__eyebrow">
          Summary · {humanLabel(measure || "")}
          {change && <> · {change.b.label} vs {change.a.label}</>}
        </div>
        {change === null && <div className="skeleton summary__skel" aria-busy="true" aria-label="Loading summary" />}
        {change && (
          <p className="summary__headline">
            <span className={`summary__pct summary__pct--${dir}`}>
              {pctText(change.pct) || `${change.delta >= 0 ? "+" : "−"}${formatNumber(Math.abs(change.delta), subtype)}`}
            </span>
            {change.summary}
          </p>
        )}
        <div className="summary__chips">
          {sig && (
            <span className={`signif__badge signif--${sig.level}`}>
              {sig.level === "normal" ? "Normal move" : sig.level === "notable" ? "Notable move" : "Unusual move"}
            </span>
          )}
          {change?.like_for_like && <span className="summary__chip">Like-for-like days</span>}
          {target && target.status !== "broken" && (
            <span className={`summary__chip target--${target.status}`}>
              Target {target.period}: {TARGET_STATUS[target.status]}
              {target.projected_ratio != null && ` · pace ${Math.round(target.projected_ratio * 100)}%`}
            </span>
          )}
        </div>
        {change && (
          <button className="link-btn summary__why" onClick={() => onOpen({ measure, tab: "change", compare: "previous" })}>
            See why it changed <Icon name="chevronRight" size={14} />
          </button>
        )}
      </div>

      {top.length > 0 && (
        <div className="summary__actions">
          <div className="summary__eyebrow">What to do</div>
          <ol>
            {top.map((a) => (
              <li key={a.id} className={`summary-action summary-action--${a.severity}`}>
                <span className="summary-action__sev">{SEV_LABEL[a.severity]}</span>
                <button className="summary-action__title" onClick={() => onOpen(a.evidence)}>
                  {a.title} <Icon name="chevronRight" size={14} />
                </button>
              </li>
            ))}
          </ol>
          {actions.length > top.length && (
            <button className="link-btn" onClick={onSeeActions}>All {actions.length} recommended actions</button>
          )}
        </div>
      )}
    </section>
  );
}
