import { useEffect, useState } from "react";
import { createSource, deleteSource, listSources, syncSource } from "../api";

const REFRESH_OPTIONS = [
  { value: 0, label: "Manual only" },
  { value: 15, label: "Every 15 min" },
  { value: 60, label: "Hourly" },
  { value: 360, label: "Every 6 hours" },
  { value: 1440, label: "Daily" },
];

const STATUS_LABEL = { ok: "Synced", error: "Error", pending: "Not synced yet" };

function relTime(iso) {
  if (!iso) return "never";
  const then = new Date(iso.replace(" ", "T"));
  const secs = Math.max(0, (Date.now() - then.getTime()) / 1000);
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)} min ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)} h ago`;
  return `${Math.floor(secs / 86400)} d ago`;
}

export default function ConnectSource({ onClose, onConnected }) {
  const [kind, setKind] = useState("google_sheet");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [sources, setSources] = useState([]);
  const [syncing, setSyncing] = useState(null);

  const load = () => listSources().then(setSources).catch(() => {});
  useEffect(() => { load(); }, []);

  const connect = async (e) => {
    e.preventDefault();
    if (!name.trim() || !url.trim()) { setError("Give the source a name and a URL."); return; }
    setBusy(true); setError(null);
    try {
      const res = await createSource(name.trim(), kind, url.trim(), Number(refresh));
      await load();
      if (res?.sync?.status === "error") {
        setError(`Created, but the first sync failed: ${res.sync.error}`);
      } else {
        setName(""); setUrl("");
        if (res?.sync?.dataset_id) onConnected?.(res.sync.dataset_id);
      }
    } catch (err) {
      setError(err?.response?.data?.detail || "Could not connect the source.");
    } finally {
      setBusy(false);
    }
  };

  const resync = async (src) => {
    setSyncing(src.source_id); setError(null);
    try {
      const r = await syncSource(src.source_id);
      await load();
      if (r?.dataset_id) onConnected?.(r.dataset_id);
    } catch (err) {
      setError(err?.response?.data?.detail || "Sync failed.");
      await load();
    } finally {
      setSyncing(null);
    }
  };

  const remove = async (src) => {
    setError(null);
    try { await deleteSource(src.source_id); await load(); }
    catch (err) { setError(err?.response?.data?.detail || "Could not remove the source."); }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal--wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal__header">
          <h3>Connect a live data source</h3>
          <button onClick={onClose}>Close</button>
        </div>
        <p className="modal__hint">
          Point InsightHub at a Google Sheet or a public CSV link. It builds a dashboard from the
          data and can re-sync on a schedule — no re-uploading each time.
        </p>

        <form className="src-form" onSubmit={connect}>
          <div className="src-field">
            <label>Type</label>
            <select value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="google_sheet">Google Sheet</option>
              <option value="url_csv">CSV URL</option>
            </select>
          </div>
          <div className="src-field src-field--grow">
            <label>Name</label>
            <input value={name} placeholder="e.g. Monthly sales" onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="src-field src-field--full">
            <label>{kind === "google_sheet" ? "Google Sheet link" : "CSV URL"}</label>
            <input
              value={url}
              placeholder={kind === "google_sheet"
                ? "https://docs.google.com/spreadsheets/d/…"
                : "https://…/data.csv"}
              onChange={(e) => setUrl(e.target.value)}
            />
            {kind === "google_sheet" && (
              <div className="src-help">
                In Google Sheets: <b>Share → Anyone with the link → Viewer</b>, then paste the link.
              </div>
            )}
          </div>
          <div className="src-field">
            <label>Auto-refresh</label>
            <select value={refresh} onChange={(e) => setRefresh(Number(e.target.value))}>
              {REFRESH_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>
          <div className="src-field src-field--action">
            <button className="src-connect" type="submit" disabled={busy}>
              {busy ? "Connecting…" : "Connect & sync"}
            </button>
          </div>
        </form>

        {error && <div className="dq-error">{error}</div>}

        {sources.length > 0 && (
          <>
            <div className="section-title" style={{ marginTop: 18 }}>Connected sources</div>
            <table className="schema-table">
              <thead>
                <tr><th>Name</th><th>Type</th><th>Status</th><th>Rows</th><th>Last sync</th><th>Refresh</th><th /></tr>
              </thead>
              <tbody>
                {sources.map((s) => (
                  <tr key={s.source_id}>
                    <td>{s.name}</td>
                    <td>{s.kind === "google_sheet" ? "Google Sheet" : "CSV URL"}</td>
                    <td>
                      <span className={`src-badge src-badge--${s.status}`} title={s.last_error || ""}>
                        {STATUS_LABEL[s.status] || s.status}
                      </span>
                    </td>
                    <td>{s.row_count?.toLocaleString("en-IN") || "—"}</td>
                    <td>{relTime(s.last_synced)}</td>
                    <td>{REFRESH_OPTIONS.find((o) => o.value === s.refresh_interval_minutes)?.label
                      || `${s.refresh_interval_minutes} min`}</td>
                    <td className="src-row-actions">
                      <button disabled={syncing === s.source_id} onClick={() => resync(s)}>
                        {syncing === s.source_id ? "…" : "Sync now"}
                      </button>
                      <button className="src-remove" onClick={() => remove(s)}>Remove</button>
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
