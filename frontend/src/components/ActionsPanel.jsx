import { useEffect, useState } from "react";
import { getActions } from "../api";

const SEVERITY_LABEL = { high: "Act now", medium: "Worth a look", low: "Opportunity" };

/**
 * Recommended actions: rule-based next steps computed from the data. Each says
 * what to do, why (with the numbers), and opens the evidence that proves it.
 */
// `data` may be passed in when the dashboard already fetched it (the summary
// card shares the same list); otherwise the panel fetches its own.
export default function ActionsPanel({ datasetId, measure, filters, refreshKey, onOpen, data: given }) {
  const [fetched, setFetched] = useState(null);
  const data = given !== undefined ? given : fetched;
  const setData = setFetched;
  const key = JSON.stringify([datasetId, measure, filters, refreshKey, given !== undefined]);

  useEffect(() => {
    if (given !== undefined) return undefined;
    let live = true;
    getActions(datasetId, { measure, filters })
      .then((d) => { if (live) setData(d); })
      .catch(() => { if (live) setData(null); });
    return () => { live = false; };
    // inputs are captured through key
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  if (!data || data.actions.length === 0) return null;
  return (
    <div className="actions" id="recommended-actions">
      <div className="insights__title">
        Recommended actions <span className="insights__auto">rules over your numbers — open the evidence behind each</span>
      </div>
      <ol className="actions__list">
        {data.actions.map((a) => (
          <li key={a.id} className={`action action--${a.severity}`}>
            <span className="action__sev">{SEVERITY_LABEL[a.severity]}</span>
            <div className="action__body">
              <div className="action__title">{a.title}</div>
              <div className="action__why">{a.why}</div>
              <div className="action__do">→ {a.action}</div>
            </div>
            <button className="views-btn action__go no-export" onClick={() => onOpen(a.evidence)}>
              See the evidence ›
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}
