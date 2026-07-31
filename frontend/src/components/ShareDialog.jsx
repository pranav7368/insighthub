import { useEffect, useState } from "react";
import { createShare, listShares, listViews, revokeShare } from "../api";

const EXPIRY_OPTIONS = [
  { value: 0, label: "Never expires" },
  { value: 7, label: "In 7 days" },
  { value: 30, label: "In 30 days" },
  { value: 90, label: "In 90 days" },
];

const fullUrl = (path) => `${window.location.origin}${path}`;

export default function ShareDialog({ datasetId, onClose }) {
  const [views, setViews] = useState([]);
  const [shares, setShares] = useState([]);
  const [viewId, setViewId] = useState("");
  const [label, setLabel] = useState("");
  const [expiry, setExpiry] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(null);

  const load = () => {
    listShares(datasetId).then(setShares).catch(() => setShares([]));
    listViews(datasetId).then(setViews).catch(() => setViews([]));
  };
  useEffect(() => { load(); }, [datasetId]);

  const create = async (e) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      await createShare(datasetId, {
        view_id: viewId || null,
        label: label.trim() || null,
        expires_in_days: Number(expiry) || null,
      });
      setLabel("");
      load();
    } catch (err) {
      setError(err?.response?.data?.detail || "Could not create the link.");
    } finally {
      setBusy(false);
    }
  };

  const copy = async (share) => {
    try {
      await navigator.clipboard.writeText(fullUrl(share.path));
      setCopied(share.token);
      setTimeout(() => setCopied(null), 1500);
    } catch { /* clipboard blocked; the link is visible to select manually */ }
  };

  const revoke = async (share) => {
    setError(null);
    try { await revokeShare(share.token); load(); }
    catch (err) { setError(err?.response?.data?.detail || "Could not revoke."); }
  };

  const activeShares = shares.filter((s) => !s.revoked);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal--wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal__header">
          <h3>Share dashboard</h3>
          <button onClick={onClose}>Close</button>
        </div>
        <p className="modal__hint">
          Create a read-only link anyone can open — no account needed. Pin a saved view to control
          exactly what they see. Revoke any link at any time.
        </p>

        <form className="src-form" onSubmit={create}>
          <div className="src-field src-field--grow">
            <label>What to share</label>
            <select value={viewId} onChange={(e) => setViewId(e.target.value)}>
              <option value="">Full dashboard (default)</option>
              {views.map((v) => (
                <option key={v.view_id} value={v.view_id}>View: {v.name}</option>
              ))}
            </select>
          </div>
          <div className="src-field src-field--grow">
            <label>Label (optional)</label>
            <input value={label} placeholder="e.g. Board deck" onChange={(e) => setLabel(e.target.value)} />
          </div>
          <div className="src-field">
            <label>Expiry</label>
            <select value={expiry} onChange={(e) => setExpiry(Number(e.target.value))}>
              {EXPIRY_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>
          <div className="src-field src-field--action">
            <button className="src-connect" type="submit" disabled={busy}>
              {busy ? "Creating…" : "Create link"}
            </button>
          </div>
        </form>

        {error && <div className="dq-error">{error}</div>}

        {activeShares.length > 0 && (
          <>
            <div className="section-title" style={{ marginTop: 18 }}>Active links</div>
            <div className="share-list">
              {activeShares.map((s) => (
                <div className="share-row" key={s.token}>
                  <div className="share-row__main">
                    {s.label && <div className="share-row__label">{s.label}</div>}
                    <input className="share-row__url" readOnly value={fullUrl(s.path)}
                      onFocus={(e) => e.target.select()} />
                    <div className="share-row__meta">
                      {s.view_id ? "Pinned view" : "Full dashboard"}
                      {s.expires_at ? ` · expires ${s.expires_at.slice(0, 10)}` : " · no expiry"}
                    </div>
                  </div>
                  <div className="share-row__actions">
                    <button onClick={() => copy(s)}>{copied === s.token ? "Copied ✓" : "Copy"}</button>
                    <button className="src-remove" onClick={() => revoke(s)}>Revoke</button>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
