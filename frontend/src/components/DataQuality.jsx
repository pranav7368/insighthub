import { useEffect, useState } from "react";
import { applyClean, errorText, getQuality } from "../api";
import { humanLabel } from "../format";

const ACTION_LABEL = {
  drop_duplicates: "Remove duplicates",
  fill_median: "Fill with median",
  fill_mean: "Fill with mean",
  fill_mode: "Fill with most common",
};

export default function DataQuality({ datasetId, onClose, onChanged }) {
  const [report, setReport] = useState(null);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);

  const load = async () => {
    setError(null);
    try {
      setReport(await getQuality(datasetId));
    } catch (err) {
      setError(errorText(err, "Could not load quality report"));
    }
  };
  useEffect(() => { load(); }, [datasetId]);

  const run = async (action, column) => {
    setBusy(`${action}:${column || ""}`);
    try {
      await applyClean(datasetId, action, column);
      await load();
      onChanged?.();
    } catch (err) {
      setError(errorText(err, "Action failed"));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal--wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal__header">
          <h3>Data quality</h3>
          <button onClick={onClose}>Close</button>
        </div>

        {error && <div className="dq-error">{error}</div>}
        {!report ? (
          <p className="modal__hint">Analysing…</p>
        ) : (
          <>
            <div className="quality-stats">
              <div className="quality-stat">
                <div className="quality-stat__value">{report.completeness_pct}%</div>
                <div className="quality-stat__label">complete</div>
              </div>
              <div className="quality-stat">
                <div className="quality-stat__value">{report.row_count.toLocaleString("en-IN")}</div>
                <div className="quality-stat__label">rows</div>
              </div>
              <div className="quality-stat">
                <div className={`quality-stat__value ${report.duplicate_rows ? "warn" : ""}`}>{report.duplicate_rows}</div>
                <div className="quality-stat__label">duplicate rows</div>
              </div>
            </div>

            {report.suggestions.length > 0 && (
              <>
                <div className="section-title">Suggested fixes</div>
                <div className="quality-suggestions">
                  {report.suggestions.map((s) => (
                    <div className={`quality-sugg quality-sugg--${s.severity}`} key={s.id}>
                      <div className="quality-sugg__text">{s.detail}</div>
                      <div className="quality-sugg__actions">
                        {s.actions.map((a) => (
                          <button key={a} disabled={busy === `${a}:${s.column || ""}`}
                            onClick={() => run(a, s.column)}>
                            {busy === `${a}:${s.column || ""}` ? "…" : ACTION_LABEL[a] || a}
                          </button>
                        ))}
                        {s.actions.length === 0 && <span className="quality-sugg__note">review manually</span>}
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}

            <div className="section-title">Columns</div>
            <table className="schema-table">
              <thead>
                <tr><th>Column</th><th>Role</th><th>Missing</th><th>Outliers</th><th>Flags</th></tr>
              </thead>
              <tbody>
                {report.columns.map((c) => (
                  <tr key={c.name}>
                    <td>{humanLabel(c.name)}</td>
                    <td>{c.role}{c.subtype ? ` · ${c.subtype}` : ""}</td>
                    <td className={c.missing_pct >= 5 ? "warn" : ""}>
                      {c.missing_count ? `${c.missing_count} (${c.missing_pct}%)` : "—"}
                    </td>
                    <td>{c.outlier_count ? c.outlier_count : "—"}</td>
                    <td>{c.mixed_format ? "mixed format" : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>
    </div>
  );
}
