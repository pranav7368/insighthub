import { useState } from "react";
import { deleteTarget, errorText, setTarget } from "../api";
import { formatNumber, humanLabel } from "../format";
import { TARGET_STATUS, currentPeriod } from "../drill";

const GRAIN_LABEL = { month: "Month", quarter: "Quarter", year: "Year" };

/** Progress against the slice's target, and (for editors) setting one. */
export default function TargetPanel({ datasetId, ctx, target, subtype, lastDate, canEdit, onChanged }) {
  const [editing, setEditing] = useState(false);
  const [grain, setGrain] = useState(target?.grain && GRAIN_LABEL[target.grain] ? target.grain : "month");
  const [period, setPeriod] = useState(target?.period || currentPeriod(lastDate, "month") || "");
  const [value, setValue] = useState(target ? String(target.value) : "");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  if (!target && !canEdit) return null;
  if (!ctx.measure || ctx.agg !== "sum") return null;   // targets are totals

  const save = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await setTarget(datasetId, { measure: ctx.measure, grain, period, value: Number(value), filters: ctx.filters });
      setEditing(false);
      onChanged();
    } catch (err) {
      setError(errorText(err, "Could not save the target."));
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    setBusy(true);
    try { await deleteTarget(target.target_id); onChanged(); }
    catch (err) { setError(errorText(err, "Could not remove the target.")); }
    finally { setBusy(false); }
  };

  return (
    <section className="insp-block">
      <div className="insp-block__head">
        <h3>Target</h3>
        {canEdit && !editing && (
          <button className="link-btn" onClick={() => setEditing(true)}>{target ? "Change" : "Set a target"}</button>
        )}
      </div>

      {target && !editing && (
        <div className={`target target--${target.status}`}>
          <div className="target__head">
            <span className="target__status">{TARGET_STATUS[target.status] || target.status}</span>
            <span className="target__period">{target.period}</span>
          </div>
          {target.status === "broken" ? (
            <p className="insp-caption">{target.reason}</p>
          ) : (
            <>
              <div className="target__bar" role="img"
                aria-label={`${Math.round((target.progress || 0) * 100)}% of the target reached`}>
                <span className="target__fill" style={{ width: `${Math.min(100, (target.progress || 0) * 100)}%` }} />
                <span className="target__pace" style={{ left: `${Math.min(100, (target.projected_ratio || 0) * 100)}%` }} />
              </div>
              <p className="insp-explain">
                <b>{formatNumber(target.actual, subtype)}</b> of {formatNumber(target.value, subtype)}
                {target.days_remaining > 0 && target.days_elapsed > 0 && (
                  <> after {target.days_elapsed} of {target.days} days — at this pace{" "}
                    <b>{formatNumber(target.projection, subtype)}</b> ({Math.round(target.projected_ratio * 100)}%).</>
                )}
              </p>
              {target.needed_per_day > 0 && (
                <p className="insp-caption">
                  To hit it, the remaining {target.days_remaining} days need {formatNumber(target.needed_per_day, subtype)} a day.
                  The projection is a straight run rate (actual ÷ days elapsed × days in the period).
                </p>
              )}
            </>
          )}
        </div>
      )}
      {!target && !editing && (
        <p className="insp-caption">No target for {humanLabel(ctx.measure).toLowerCase()} on this slice yet.</p>
      )}

      {editing && (
        <form className="target-form" onSubmit={save}>
          <label>
            <span>Period</span>
            <select className="insp-select" value={grain} onChange={(e) => {
              setGrain(e.target.value);
              setPeriod(currentPeriod(lastDate, e.target.value) || "");
            }}>
              {Object.entries(GRAIN_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <label>
            <span>Which {grain}</span>
            <input className="insp-input" value={period} onChange={(e) => setPeriod(e.target.value)}
              placeholder={grain === "quarter" ? "2026-Q4" : grain === "year" ? "2026" : "2026-10"} required />
          </label>
          <label>
            <span>Target {humanLabel(ctx.measure).toLowerCase()}</span>
            <input className="insp-input" type="number" step="any" value={value}
              onChange={(e) => setValue(e.target.value)} required />
          </label>
          <div className="target-form__actions">
            <button className="views-btn views-btn--accent" disabled={busy}>Save target</button>
            <button type="button" className="views-btn" onClick={() => setEditing(false)}>Cancel</button>
            {target && <button type="button" className="views-btn views-btn--danger" onClick={remove} disabled={busy}>Remove</button>}
          </div>
          {Object.keys(ctx.filters || {}).length > 0 && (
            <p className="insp-caption">
              Applies to {Object.entries(ctx.filters).map(([k, v]) => `${humanLabel(k)} ${v}`).join(", ")} only.
            </p>
          )}
        </form>
      )}
      {error && <p className="form-error" role="alert">{error}</p>}
    </section>
  );
}
