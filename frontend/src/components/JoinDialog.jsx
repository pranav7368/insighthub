import { useEffect, useState } from "react";
import { createJoin, deleteJoin, listJoins, rebuildJoin, suggestJoin } from "../api";
import { humanLabel } from "../format";

export default function JoinDialog({ datasets, currentDatasetId, onClose, onCreated }) {
  const structured = datasets.filter((d) => d.kind === "structured");
  const [leftId, setLeftId] = useState(currentDatasetId || structured[0]?.dataset_id || "");
  const [rightId, setRightId] = useState("");
  const [sug, setSug] = useState(null);
  const [leftKey, setLeftKey] = useState("");
  const [rightKey, setRightKey] = useState("");
  const [joinType, setJoinType] = useState("left");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [joins, setJoins] = useState([]);

  const load = () => listJoins().then(setJoins).catch(() => setJoins([]));
  useEffect(() => { load(); }, []);

  // when both sides chosen, fetch columns + a suggested key
  useEffect(() => {
    if (!leftId || !rightId || leftId === rightId) { setSug(null); return; }
    suggestJoin(leftId, rightId)
      .then((s) => {
        setSug(s);
        setLeftKey(s.suggested?.left_key || s.left_columns[0] || "");
        setRightKey(s.suggested?.right_key || s.right_columns[0] || "");
      })
      .catch(() => setSug(null));
  }, [leftId, rightId]);

  const nameOf = (id) => structured.find((d) => d.dataset_id === id)?.name || "dataset";

  const create = async (e) => {
    e.preventDefault();
    if (!leftId || !rightId || leftId === rightId) { setError("Pick two different datasets."); return; }
    if (!leftKey || !rightKey) { setError("Choose the columns to match on."); return; }
    setBusy(true); setError(null);
    try {
      const res = await createJoin({
        left_dataset_id: leftId, right_dataset_id: rightId,
        left_key: leftKey, right_key: rightKey, join_type: joinType, name: name.trim() || null,
      });
      load();
      if (res?.dataset_id) onCreated?.(res.dataset_id);
    } catch (err) {
      setError(err?.response?.data?.detail || "Could not create the join.");
    } finally {
      setBusy(false);
    }
  };

  const rebuild = async (j) => {
    setError(null);
    try { await rebuildJoin(j.relation_id); load(); }
    catch (err) { setError(err?.response?.data?.detail || "Rebuild failed."); }
  };
  const remove = async (j) => {
    setError(null);
    try { await deleteJoin(j.relation_id); load(); }
    catch (err) { setError(err?.response?.data?.detail || "Could not delete."); }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal--wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal__header">
          <h3>Link datasets</h3>
          <button onClick={onClose}>Close</button>
        </div>
        <p className="modal__hint">
          Combine two datasets on a shared column (e.g. orders + customers on <i>customer_id</i>). The
          joined result becomes a new dataset you can dashboard, ask, and analyse like any other.
        </p>

        {structured.length < 2 ? (
          <div className="empty-panel">You need at least two spreadsheet datasets to link.</div>
        ) : (
          <form className="join-form" onSubmit={create}>
            <div className="join-row">
              <div className="src-field src-field--grow">
                <label>Left dataset</label>
                <select value={leftId} onChange={(e) => setLeftId(e.target.value)}>
                  {structured.map((d) => <option key={d.dataset_id} value={d.dataset_id}>{d.name}</option>)}
                </select>
              </div>
              <div className="src-field src-field--grow">
                <label>Right dataset</label>
                <select value={rightId} onChange={(e) => setRightId(e.target.value)}>
                  <option value="">Choose…</option>
                  {structured.filter((d) => d.dataset_id !== leftId)
                    .map((d) => <option key={d.dataset_id} value={d.dataset_id}>{d.name}</option>)}
                </select>
              </div>
            </div>

            {sug && (
              <>
                <div className="join-row">
                  <div className="src-field src-field--grow">
                    <label>Match {nameOf(leftId)} column</label>
                    <select value={leftKey} onChange={(e) => setLeftKey(e.target.value)}>
                      {sug.left_columns.map((c) => <option key={c} value={c}>{humanLabel(c)}</option>)}
                    </select>
                  </div>
                  <div className="join-eq">=</div>
                  <div className="src-field src-field--grow">
                    <label>with {nameOf(rightId)} column</label>
                    <select value={rightKey} onChange={(e) => setRightKey(e.target.value)}>
                      {sug.right_columns.map((c) => <option key={c} value={c}>{humanLabel(c)}</option>)}
                    </select>
                  </div>
                </div>
                {sug.common?.length === 0 && (
                  <div className="join-note">No obviously-shared column — pick the matching keys manually.</div>
                )}
                <div className="join-row join-row--opts">
                  <div className="src-field">
                    <label>Join type</label>
                    <select value={joinType} onChange={(e) => setJoinType(e.target.value)}>
                      <option value="left">Keep all left rows (left join)</option>
                      <option value="inner">Only matching rows (inner join)</option>
                    </select>
                  </div>
                  <div className="src-field src-field--grow">
                    <label>New dataset name (optional)</label>
                    <input value={name} placeholder={`${nameOf(leftId)} + ${nameOf(rightId)}`}
                      onChange={(e) => setName(e.target.value)} />
                  </div>
                  <div className="src-field src-field--action">
                    <button className="src-connect" type="submit" disabled={busy}>
                      {busy ? "Joining…" : "Create joined dataset"}
                    </button>
                  </div>
                </div>
              </>
            )}
          </form>
        )}

        {error && <div className="dq-error">{error}</div>}

        {joins.length > 0 && (
          <>
            <div className="section-title" style={{ marginTop: 18 }}>Linked datasets</div>
            <table className="schema-table">
              <thead><tr><th>Joined dataset</th><th>From</th><th>On</th><th>Rows</th><th /></tr></thead>
              <tbody>
                {joins.map((j) => (
                  <tr key={j.relation_id}>
                    <td>{j.name}</td>
                    <td>{j.left_name} + {j.right_name}</td>
                    <td>{humanLabel(j.left_key)} = {humanLabel(j.right_key)} ({j.join_type})</td>
                    <td>{j.row_count?.toLocaleString("en-IN")}</td>
                    <td className="src-row-actions">
                      <button onClick={() => rebuild(j)}>Rebuild</button>
                      <button className="src-remove" onClick={() => remove(j)}>Delete</button>
                    </td>
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
