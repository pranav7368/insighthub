import { useEffect, useRef, useState } from "react";
import { appendData, getBatches, rollbackBatch } from "../api";

export default function UpdateData({ datasetId, datasetName, onClose, onChanged }) {
  const [mode, setMode] = useState("append");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [batches, setBatches] = useState([]);
  const [undoing, setUndoing] = useState(null);
  const inputRef = useRef(null);

  const loadBatches = () => getBatches(datasetId).then(setBatches).catch(() => {});
  useEffect(() => { loadBatches(); }, [datasetId]);

  const pickFile = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setBusy(true); setError(null); setResult(null);
    try {
      const r = await appendData(datasetId, file, mode);
      setResult(r);
      await loadBatches();
      onChanged?.();
    } catch (err) {
      setError(err?.response?.data?.detail || "Update failed");
    } finally {
      setBusy(false);
    }
  };

  const undo = async (batchId) => {
    setUndoing(batchId); setError(null);
    try {
      await rollbackBatch(datasetId, batchId);
      await loadBatches();
      setResult(null);
      onChanged?.();
    } catch (err) {
      setError(err?.response?.data?.detail || "Undo failed");
    } finally {
      setUndoing(null);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal--wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal__header">
          <h3>Update “{datasetName}”</h3>
          <button onClick={onClose}>Close</button>
        </div>
        <p className="modal__hint">
          Add a new file (e.g. next month’s report) into this dataset. Re-uploading the same file is safe —
          identical rows are skipped, never double-counted.
        </p>

        <div className="upd-modes">
          <label className={mode === "append" ? "upd-mode active" : "upd-mode"}>
            <input type="radio" checked={mode === "append"} onChange={() => setMode("append")} />
            <div>
              <div className="upd-mode__title">Add new data</div>
              <div className="upd-mode__sub">Append the rows in this file (new period).</div>
            </div>
          </label>
          <label className={mode === "replace_period" ? "upd-mode active" : "upd-mode"}>
            <input type="radio" checked={mode === "replace_period"} onChange={() => setMode("replace_period")} />
            <div>
              <div className="upd-mode__title">Correct a period</div>
              <div className="upd-mode__sub">Replace existing rows for the months this file covers (restatement).</div>
            </div>
          </label>
        </div>

        <button className="upd-upload" onClick={() => inputRef.current?.click()} disabled={busy}>
          {busy ? "Processing…" : "Choose file (CSV/XLSX)"}
        </button>
        <input ref={inputRef} type="file" accept=".csv,.xlsx,.xlsm" hidden onChange={pickFile} />

        {error && <div className="dq-error">{error}</div>}

        {result && (
          <div className="upd-result">
            <div className="upd-result__head">
              <b>+{result.rows_added}</b> added
              {result.rows_removed > 0 && <> · <b>−{result.rows_removed}</b> replaced</>}
              {result.skipped_duplicates > 0 && <> · {result.skipped_duplicates} duplicate(s) skipped</>}
              · now {result.row_count.toLocaleString("en-IN")} rows
            </div>
            {result.warnings?.map((w, i) => <div className="upd-warn" key={i}>• {w}</div>)}
          </div>
        )}

        <div className="section-title" style={{ marginTop: 18 }}>Import history</div>
        <table className="schema-table">
          <thead><tr><th>When</th><th>File</th><th>Type</th><th>Added</th><th>Replaced</th><th /></tr></thead>
          <tbody>
            {batches.map((b) => (
              <tr key={b.batch_id}>
                <td>{b.created_at?.slice(0, 16).replace("T", " ")}</td>
                <td>{b.source_file}</td>
                <td>{b.mode}</td>
                <td>+{b.rows_added}</td>
                <td>{b.rows_removed || "—"}</td>
                <td>
                  {b.mode !== "initial" && (
                    <button className="upd-undo" disabled={undoing === b.batch_id} onClick={() => undo(b.batch_id)}>
                      {undoing === b.batch_id ? "…" : "Undo"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
