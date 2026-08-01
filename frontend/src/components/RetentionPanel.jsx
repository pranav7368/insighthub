import { useEffect, useState } from "react";
import { errorText, getRetention, previewRetention, runRetention, setRetention } from "../api";

const FIELDS = [
  ["audit_days", "Activity log", "Who did what, and when."],
  ["archive_days", "Undo history", "Snapshots kept so a data update can be rolled back."],
  ["dataset_days", "Uploaded data", "The datasets themselves. Deleting these cannot be undone."],
];

/**
 * Retention settings.
 *
 * This is the only screen in the product that arms unattended deletion of
 * customer data, so it is built to be hard to use carelessly: everything reads
 * "keep forever" until changed, and Preview — which deletes nothing — is the
 * obvious next step rather than Save.
 *
 * Scope note: retention is WORKSPACE-wide, unlike the row access and masking
 * rules above it, which is stated in the UI rather than left to be discovered.
 */
export default function RetentionPanel() {
  const [policy, setPolicy] = useState(null);
  const [draft, setDraft] = useState({ audit_days: 0, archive_days: 0, dataset_days: 0 });
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getRetention()
      .then((p) => {
        setPolicy(p);
        setDraft({ audit_days: p.audit_days, archive_days: p.archive_days,
                   dataset_days: p.dataset_days });
      })
      .catch((err) => setError(errorText(err, "Could not load retention settings.")));
  }, []);

  const change = (key, value) => {
    setDraft((d) => ({ ...d, [key]: Number(value) || 0 }));
    setPreview(null);        // a stale preview is worse than none
    setSaved(false);
  };

  const check = async () => {
    setBusy(true); setError(null);
    try { setPreview(await previewRetention(draft)); }
    catch (err) { setError(errorText(err, "Could not check that policy.")); }
    finally { setBusy(false); }
  };

  const save = async () => {
    setBusy(true); setError(null);
    try {
      await setRetention(draft);
      setPolicy(await getRetention());     // re-read, so the floors come back too
      setSaved(true);
      setPreview(null);
    } catch (err) { setError(errorText(err, "Could not save that policy.")); }
    finally { setBusy(false); }
  };

  const runNow = async () => {
    setBusy(true); setError(null);
    try {
      const result = await runRetention();
      setPreview({ ...result, ran: true });
    } catch (err) { setError(errorText(err, "Could not run the sweep.")); }
    finally { setBusy(false); }
  };

  // A failed load must not sit on "Loading…" forever with the reason hidden.
  if (!policy) {
    return error
      ? <div className="tpl-error">{error}</div>
      : <div className="access-empty">Loading…</div>;
  }

  const nothingSet = !draft.audit_days && !draft.archive_days && !draft.dataset_days;
  const changed = FIELDS.some(([k]) => draft[k] !== policy[k]);

  return (
    <>
      <p className="access-note">
        Applies to the <b>whole workspace</b>, not just this dataset. Leave a field at 0 to
        keep that data forever — nothing is ever deleted unless you set a period here.
      </p>

      {/* a rejected period has to be visible here; the parent dialog tracks
          its own errors and never sees this one */}
      {error && <div className="tpl-error">{error}</div>}

      <div className="ret-grid">
        {FIELDS.map(([key, label, help]) => (
          <label key={key} className="ret-field">
            <span className="ret-field__label">{label}</span>
            <span className="ret-field__help">{help}</span>
            <span className="ret-field__input">
              <input type="number" min="0" value={draft[key]}
                onChange={(e) => change(key, e.target.value)} aria-label={label} />
              <span>{draft[key] === 0 ? "keep forever" : "days"}</span>
            </span>
          </label>
        ))}
      </div>

      <p className="access-note">
        Minimum {policy.minimum_days} days, or {policy.minimum_dataset_days} for uploaded
        data — a very short period would delete history the same night it is set.
      </p>

      <div className="sec-inline">
        <button className="views-btn" onClick={check} disabled={busy || nothingSet}>
          {busy ? "Checking…" : "Preview what this deletes"}
        </button>
        <button className="views-btn views-btn--accent" onClick={save} disabled={busy || !changed}>
          Save policy
        </button>
        {!nothingSet && !changed && (
          <button className="views-btn" onClick={runNow} disabled={busy}>Run sweep now</button>
        )}
        {saved && <span className="src-badge src-badge--ok">Saved</span>}
      </div>

      {preview && (
        <div className="ret-preview">
          <b>{preview.ran ? "Sweep complete." : "This policy would delete:"}</b>
          <ul>
            <li>{preview.audit_entries} activity log entries</li>
            <li>{preview.archived_rows} archived rows</li>
            <li>
              {preview.datasets.length} dataset{preview.datasets.length === 1 ? "" : "s"}
              {preview.datasets.length > 0 && (
                <> — {preview.datasets.map((d) => d.name).join(", ")}</>
              )}
            </li>
          </ul>
          {!preview.ran && (
            <span className="ret-preview__note">Nothing has been deleted. Save the policy to arm it.</span>
          )}
        </div>
      )}
    </>
  );
}
