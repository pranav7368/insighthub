import { useCallback, useEffect, useState } from "react";
import {
  createReport, deleteReport, errorText, getReportsStatus, getSchema, listReports, previewReport,
  sendReportNow, setReportEnabled,
} from "../api";
import { humanLabel } from "../format";

const FREQUENCIES = [
  { value: "daily", label: "Every day" },
  { value: "weekly", label: "Every week" },
  { value: "monthly", label: "Every month" },
];

/**
 * Scheduled email reports: the headline change, key numbers, where the
 * change came from, targets and recommended actions — computed, masked, and
 * sent on a schedule. The preview is exactly what a recipient receives.
 */
export default function ReportsDialog({ datasetId, onClose }) {
  const [reports, setReports] = useState([]);
  const [measures, setMeasures] = useState([]);
  const [configured, setConfigured] = useState(true);
  const [form, setForm] = useState({ name: "", recipients: "", frequency: "weekly", measure: "" });
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [note, setNote] = useState(null);

  const load = useCallback(() => listReports(datasetId).then(setReports).catch(() => setReports([])), [datasetId]);
  useEffect(() => {
    load();
    getReportsStatus().then((s) => setConfigured(s.email_configured)).catch(() => {});
    getSchema(datasetId).then((cols) => {
      const m = cols.filter((c) => c.role === "measure");
      setMeasures(m);
      setForm((f) => ({ ...f, measure: f.measure || m[0]?.name || "" }));
    }).catch(() => setMeasures([]));
  }, [datasetId, load]);

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const run = async (fn, okNote) => {
    setBusy(true); setError(null); setNote(null);
    try { await fn(); if (okNote) setNote(okNote); }
    catch (err) { setError(errorText(err, "That did not work.")); }
    finally { setBusy(false); }
  };

  const create = (e) => {
    e.preventDefault();
    run(async () => {
      await createReport(datasetId, { ...form, measure: form.measure || null });
      setForm((f) => ({ ...f, name: "", recipients: "" }));
      await load();
    });
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal--wide" role="dialog" aria-modal="true" aria-label="Email reports"
        onClick={(e) => e.stopPropagation()}>
        <div className="modal__header">
          <h3>Email reports</h3>
          <button onClick={onClose}>Close</button>
        </div>
        <p className="modal__hint">
          A summary of what changed, why, your targets and the recommended actions — computed from the data and
          emailed on a schedule. Names that could identify a person are always masked in emails.
        </p>
        {!configured && (
          <div className="dq-error">
            Email is not configured on this server yet. Reports can be scheduled and previewed, but sending
            needs <code>IH_SMTP_HOST</code> (and usually <code>IH_SMTP_USER</code> / <code>IH_SMTP_PASSWORD</code>).
          </div>
        )}

        <form className="alert-form" onSubmit={create}>
          <div className="src-field src-field--grow">
            <label htmlFor="rpt-name">Name</label>
            <input id="rpt-name" value={form.name} placeholder="e.g. Weekly revenue" onChange={(e) => set("name", e.target.value)} />
          </div>
          <div className="src-field src-field--full">
            <label htmlFor="rpt-to">Recipients</label>
            <input id="rpt-to" value={form.recipients} placeholder="ceo@company.com, finance@company.com"
              onChange={(e) => set("recipients", e.target.value)} />
          </div>
          <div className="alert-cond">
            <label htmlFor="rpt-measure">About</label>
            <select id="rpt-measure" value={form.measure} onChange={(e) => set("measure", e.target.value)}>
              {measures.map((m) => <option key={m.name} value={m.name}>{humanLabel(m.name)}</option>)}
            </select>
            <select aria-label="How often" value={form.frequency} onChange={(e) => set("frequency", e.target.value)}>
              {FREQUENCIES.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
            </select>
            <button type="button" className="views-btn" disabled={busy}
              onClick={() => run(async () => setPreview(await previewReport(datasetId, form.measure)))}>
              Preview
            </button>
          </div>
          <div className="src-field src-field--action">
            <button className="src-connect" type="submit" disabled={busy || !form.name.trim() || !form.recipients.trim()}>
              Schedule report
            </button>
          </div>
        </form>

        {error && <div className="dq-error" role="alert">{error}</div>}
        {note && <div className="dq-note" role="status">{note}</div>}

        {preview && (
          <div className="report-preview">
            <div className="report-preview__subject"><b>Subject:</b> {preview.subject}</div>
            {/* the email's own HTML, sandboxed: no scripts, no same-origin access */}
            <iframe title="Email preview" sandbox="" srcDoc={preview.html} className="report-preview__frame" />
          </div>
        )}

        <ul className="report-list">
          {reports.length === 0 && <li className="access-empty">No reports scheduled yet.</li>}
          {reports.map((r) => (
            <li key={r.report_id} className="report-row">
              <div className="report-row__main">
                <b>{r.name}</b> · {FREQUENCIES.find((f) => f.value === r.frequency)?.label.toLowerCase()} ·{" "}
                {humanLabel(r.measure || "default measure")}
                <div className="report-row__meta">
                  To {r.recipients.join(", ")}
                  {r.last_sent_at && <> · last sent {r.last_sent_at.slice(0, 16)}</>}
                  {r.last_status === "error" && <span className="report-row__err"> · failed: {r.last_error}</span>}
                  {!r.enabled && <> · paused</>}
                </div>
              </div>
              <div className="report-row__actions">
                <button className="views-btn" disabled={busy}
                  onClick={() => run(async () => { const o = await sendReportNow(r.report_id); await load(); return o; },
                    `Sent “${r.name}” to ${r.recipients.length} recipient${r.recipients.length === 1 ? "" : "s"}.`)}>
                  Send now
                </button>
                <button className="views-btn" disabled={busy}
                  onClick={() => run(async () => { await setReportEnabled(r.report_id, !r.enabled); await load(); })}>
                  {r.enabled ? "Pause" : "Resume"}
                </button>
                <button className="views-btn views-btn--danger" disabled={busy}
                  onClick={() => run(async () => { await deleteReport(r.report_id); await load(); })}>
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
