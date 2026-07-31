import { useEffect, useState } from "react";
import { createMetric, deleteMetric, errorText, getSchema, listMetrics } from "../api";
import { humanLabel } from "../format";

const AGGS = [
  { value: "sum", label: "Sum" },
  { value: "avg", label: "Average" },
  { value: "min", label: "Min" },
  { value: "max", label: "Max" },
  { value: "median", label: "Median" },
  { value: "count", label: "Count of rows" },
  { value: "count_distinct", label: "Count distinct" },
];
const FORMATS = [
  { value: "number", label: "Number" },
  { value: "currency", label: "Currency (₹)" },
  { value: "percent", label: "Percent" },
];

// count -> count(*), needs no column; everything else needs a column
const needsColumn = (agg) => agg !== "count";

function SpecFields({ spec, columns, onChange }) {
  return (
    <>
      <select value={spec.agg} onChange={(e) => onChange({ ...spec, agg: e.target.value })}>
        {AGGS.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
      </select>
      <span>of</span>
      <select value={spec.column} disabled={!needsColumn(spec.agg)}
        onChange={(e) => onChange({ ...spec, column: e.target.value })}>
        {!needsColumn(spec.agg)
          ? <option value="">(rows)</option>
          : columns.map((c) => <option key={c.name} value={c.name}>{humanLabel(c.name)}</option>)}
      </select>
    </>
  );
}

export default function MetricsDialog({ datasetId, onClose, onChanged }) {
  const [columns, setColumns] = useState([]);
  const [metrics, setMetrics] = useState([]);
  const [name, setName] = useState("");
  const [kind, setKind] = useState("aggregate");
  const [format, setFormat] = useState("number");
  const [agg, setAgg] = useState({ agg: "sum", column: "" });
  const [num, setNum] = useState({ agg: "sum", column: "" });
  const [den, setDen] = useState({ agg: "sum", column: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const load = () => listMetrics(datasetId).then(setMetrics).catch(() => setMetrics([]));
  useEffect(() => {
    load();
    getSchema(datasetId)
      .then((cols) => {
        const numeric = cols.filter((c) => c.role === "measure");
        const usable = numeric.length ? numeric : cols;
        setColumns(usable);
        const first = usable[0]?.name || "";
        setAgg((s) => ({ ...s, column: s.column || first }));
        setNum((s) => ({ ...s, column: s.column || first }));
        setDen((s) => ({ ...s, column: s.column || first }));
      })
      .catch(() => setColumns([]));
  }, [datasetId]);

  const create = async (e) => {
    e.preventDefault();
    if (!name.trim()) { setError("Give the metric a name."); return; }
    const definition = kind === "aggregate" ? agg : { numerator: num, denominator: den };
    setBusy(true); setError(null);
    try {
      await createMetric(datasetId, { name: name.trim(), kind, definition, format });
      setName("");
      load();
      onChanged?.();
    } catch (err) {
      setError(errorText(err, "Could not create the metric."));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (m) => {
    try { await deleteMetric(m.metric_id); load(); onChanged?.(); }
    catch (err) { setError(errorText(err, "Could not delete.")); }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal--wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal__header">
          <h3>Certified metrics</h3>
          <button onClick={onClose}>Close</button>
        </div>
        <p className="modal__hint">
          Define a metric once — an aggregate like <i>Sum of revenue</i>, or a ratio like
          <i> Sum of profit ÷ Sum of revenue</i> — and it’s computed the same way everywhere, with the
          exact SQL shown on the dashboard. No formulas to copy around.
        </p>

        {columns.length === 0 ? (
          <div className="empty-panel">This dataset has no numeric columns to build a metric from.</div>
        ) : (
          <form className="alert-form" onSubmit={create}>
            <div className="src-field src-field--grow">
              <label>Name</label>
              <input value={name} placeholder="e.g. Gross margin" onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="src-field">
              <label>Type</label>
              <select value={kind} onChange={(e) => setKind(e.target.value)}>
                <option value="aggregate">Aggregate</option>
                <option value="ratio">Ratio (a ÷ b)</option>
              </select>
            </div>
            <div className="src-field">
              <label>Format</label>
              <select value={format} onChange={(e) => setFormat(e.target.value)}>
                {FORMATS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
              </select>
            </div>
            <div className="alert-cond metric-def">
              {kind === "aggregate" ? (
                <SpecFields spec={agg} columns={columns} onChange={setAgg} />
              ) : (
                <>
                  <SpecFields spec={num} columns={columns} onChange={setNum} />
                  <span className="metric-div">÷</span>
                  <SpecFields spec={den} columns={columns} onChange={setDen} />
                </>
              )}
            </div>
            <div className="src-field src-field--action">
              <button className="src-connect" type="submit" disabled={busy}>
                {busy ? "Creating…" : "Create metric"}
              </button>
            </div>
          </form>
        )}

        {error && <div className="dq-error">{error}</div>}

        {metrics.length > 0 && (
          <>
            <div className="section-title" style={{ marginTop: 18 }}>Defined metrics</div>
            <table className="schema-table">
              <thead><tr><th>Name</th><th>Value</th><th>SQL</th><th /></tr></thead>
              <tbody>
                {metrics.map((m) => (
                  <tr key={m.metric_id}>
                    <td>{m.name}</td>
                    <td>{m.error ? "—" : (m.value ?? "—")}</td>
                    <td><code className="metric-sql-inline">{m.sql || m.error}</code></td>
                    <td><button className="src-remove" onClick={() => remove(m)}>Delete</button></td>
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
