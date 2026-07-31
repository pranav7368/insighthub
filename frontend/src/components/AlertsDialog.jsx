import { useEffect, useState } from "react";
import { createAlert, deleteAlert, getSchema, listAlerts, setAlertEnabled, testAlert } from "../api";
import { humanLabel } from "../format";

const AGGREGATES = [
  { value: "total", label: "Total" },
  { value: "latest", label: "Latest month" },
  { value: "mom_pct", label: "Month-over-month %" },
];
const OPS = [
  { value: "lt", label: "is below" },
  { value: "lte", label: "is at or below" },
  { value: "gt", label: "is above" },
  { value: "gte", label: "is at or above" },
];
const STATE_LABEL = { firing: "Firing", ok: "OK", error: "Error", pending: "Waiting for data" };

export default function AlertsDialog({ datasetId, onClose }) {
  const [measures, setMeasures] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [form, setForm] = useState({ name: "", measure: "", aggregate: "total", op: "lt", threshold: "", webhook_url: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [note, setNote] = useState(null);

  const load = () => listAlerts(datasetId).then(setAlerts).catch(() => setAlerts([]));
  useEffect(() => {
    load();
    getSchema(datasetId)
      .then((cols) => {
        const m = cols.filter((c) => c.role === "measure");
        setMeasures(m);
        setForm((f) => ({ ...f, measure: f.measure || m[0]?.name || "" }));
      })
      .catch(() => setMeasures([]));
  }, [datasetId]);

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const create = async (e) => {
    e.preventDefault();
    if (!form.name.trim() || !form.measure || form.threshold === "" || !form.webhook_url.trim()) {
      setError("Fill in a name, measure, threshold, and webhook URL."); return;
    }
    setBusy(true); setError(null); setNote(null);
    try {
      await createAlert(datasetId, {
        name: form.name.trim(), measure: form.measure, aggregate: form.aggregate,
        op: form.op, threshold: Number(form.threshold), webhook_url: form.webhook_url.trim(),
      });
      setForm((f) => ({ ...f, name: "", threshold: "" }));
      load();
    } catch (err) {
      setError(err?.response?.data?.detail || "Could not create the alert.");
    } finally {
      setBusy(false);
    }
  };

  const runTest = async (a) => {
    setError(null); setNote(null);
    try { await testAlert(a.alert_id); setNote(`Test sent to “${a.name}” webhook.`); }
    catch (err) { setError(err?.response?.data?.detail || "Webhook test failed."); }
  };
  const toggle = async (a) => {
    try { await setAlertEnabled(a.alert_id, !a.enabled); load(); }
    catch (err) { setError(err?.response?.data?.detail || "Could not update the alert."); }
  };
  const remove = async (a) => {
    try { await deleteAlert(a.alert_id); load(); }
    catch (err) { setError(err?.response?.data?.detail || "Could not delete the alert."); }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal--wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal__header">
          <h3>Alerts</h3>
          <button onClick={onClose}>Close</button>
        </div>
        <p className="modal__hint">
          Get notified when a metric crosses a line. InsightHub checks on a schedule and posts to your
          webhook (Slack, Teams, Discord, or any URL) — only when the condition first becomes true.
        </p>

        {measures.length === 0 ? (
          <div className="empty-panel">This dataset has no numeric measures to watch.</div>
        ) : (
          <form className="alert-form" onSubmit={create}>
            <div className="src-field src-field--grow">
              <label>Name</label>
              <input value={form.name} placeholder="e.g. Revenue crash" onChange={(e) => set("name", e.target.value)} />
            </div>
            <div className="alert-cond">
              <span>When</span>
              <select value={form.aggregate} onChange={(e) => set("aggregate", e.target.value)}>
                {AGGREGATES.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
              </select>
              <span>of</span>
              <select value={form.measure} onChange={(e) => set("measure", e.target.value)}>
                {measures.map((m) => <option key={m.name} value={m.name}>{humanLabel(m.name)}</option>)}
              </select>
              <select value={form.op} onChange={(e) => set("op", e.target.value)}>
                {OPS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
              <input className="alert-threshold" type="number" step="any" value={form.threshold}
                placeholder="value" onChange={(e) => set("threshold", e.target.value)} />
            </div>
            <div className="src-field src-field--full">
              <label>Webhook URL</label>
              <input value={form.webhook_url} placeholder="https://hooks.slack.com/services/…"
                onChange={(e) => set("webhook_url", e.target.value)} />
            </div>
            <div className="src-field src-field--action">
              <button className="src-connect" type="submit" disabled={busy}>
                {busy ? "Creating…" : "Create alert"}
              </button>
            </div>
          </form>
        )}

        {error && <div className="dq-error">{error}</div>}
        {note && <div className="alert-note">{note}</div>}

        {alerts.length > 0 && (
          <>
            <div className="section-title" style={{ marginTop: 18 }}>Your alerts</div>
            <table className="schema-table">
              <thead>
                <tr><th>Name</th><th>Condition</th><th>Status</th><th>Last value</th><th /></tr>
              </thead>
              <tbody>
                {alerts.map((a) => (
                  <tr key={a.alert_id} className={a.enabled ? "" : "alert-row--off"}>
                    <td>{a.name}</td>
                    <td className="alert-cond-cell">
                      {AGGREGATES.find((x) => x.value === a.aggregate)?.label} {humanLabel(a.measure)}{" "}
                      {OPS.find((x) => x.value === a.op)?.label} {a.threshold}
                    </td>
                    <td>
                      <span className={`src-badge alert-badge--${a.last_state}`}
                        title={a.last_error || ""}>{STATE_LABEL[a.last_state] || a.last_state}</span>
                    </td>
                    <td>{a.last_value == null ? "—" : a.last_value.toLocaleString("en-IN")}</td>
                    <td className="src-row-actions">
                      <button onClick={() => runTest(a)}>Test</button>
                      <button onClick={() => toggle(a)}>{a.enabled ? "Pause" : "Resume"}</button>
                      <button className="src-remove" onClick={() => remove(a)}>Delete</button>
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
