import { useCallback, useEffect, useState } from "react";
import { createApiKey, errorText, listApiKeys, revokeApiKey } from "../api";
import { formatDate } from "../format";
import { toast } from "../toast";

const EXPIRY = [
  { value: 90, label: "In 90 days" },
  { value: 30, label: "In 30 days" },
  { value: 365, label: "In a year" },
  { value: 0, label: "Never" },
];

const day = (iso) => (iso ? formatDate(iso.slice(0, 10)) : null);

/**
 * Admin-only: keys for scripts, BI tools and integrations. A key is shown
 * once; after that only its hint is stored anywhere we can show.
 */
export default function ApiKeysDialog({ onClose }) {
  const [keys, setKeys] = useState([]);
  const [name, setName] = useState("");
  const [role, setRole] = useState("viewer");
  const [expiry, setExpiry] = useState(90);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [fresh, setFresh] = useState(null);        // the just-created key, plain text, this once
  const [confirming, setConfirming] = useState(null);

  const load = useCallback(() => {
    listApiKeys().then(setKeys).catch((e) => setError(errorText(e, "Could not load keys.")));
  }, []);
  useEffect(() => { load(); }, [load]);

  const create = async (e) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const k = await createApiKey({ name: name.trim(), role, expires_in_days: Number(expiry) || null });
      setFresh(k);
      setName("");
      load();
    } catch (err) {
      setError(errorText(err, "Could not create the key."));
    } finally {
      setBusy(false);
    }
  };

  const copy = async (text, what) => {
    try { await navigator.clipboard.writeText(text); toast(`${what} copied`); }
    catch { /* clipboard blocked: the text is selectable */ }
  };

  const revoke = async (k) => {
    if (confirming !== k.key_id) { setConfirming(k.key_id); return; }
    setConfirming(null); setError(null);
    try { await revokeApiKey(k.key_id); toast(`Revoked “${k.name}”`); load(); }
    catch (err) { setError(errorText(err, "Could not revoke the key.")); }
  };

  const curl = fresh && `curl -H "Authorization: Bearer ${fresh.key}" ${window.location.origin}/api/datasets`;
  const active = keys.filter((k) => !k.revoked_at);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal--wide" role="dialog" aria-modal="true" aria-labelledby="apikeys-title"
        onClick={(e) => e.stopPropagation()}>
        <div className="modal__header">
          <h3 id="apikeys-title">API keys</h3>
          <button onClick={onClose}>Close</button>
        </div>
        <p className="modal__hint">
          For scripts, BI tools and integrations. A key reads (or, as an editor, writes) data only — it
          cannot manage the team, billing or privacy. It sees what you see, with personal data always
          masked, and stops working if you leave the workspace.
        </p>

        {fresh && (
          <div className="key-reveal" role="status">
            <div className="key-reveal__title">“{fresh.name}” is ready. Copy it now — it will not be shown again.</div>
            <div className="key-reveal__row">
              <input readOnly value={fresh.key} aria-label="New API key" onFocus={(e) => e.target.select()} />
              <button className="views-btn views-btn--accent" onClick={() => copy(fresh.key, "Key")}>Copy key</button>
            </div>
            <div className="key-reveal__row">
              <code className="key-reveal__curl">{curl}</code>
              <button className="views-btn" onClick={() => copy(curl, "Example")}>Copy</button>
            </div>
            <button className="link-btn" onClick={() => setFresh(null)}>I have stored it safely</button>
          </div>
        )}

        <form className="src-form" onSubmit={create}>
          <div className="src-field src-field--grow">
            <label htmlFor="key-name">Name</label>
            <input id="key-name" value={name} maxLength={80} placeholder="e.g. Power BI refresh"
              onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="src-field">
            <label htmlFor="key-role">Access</label>
            <select id="key-role" value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="viewer">Read data</option>
              <option value="editor">Read and write data</option>
            </select>
          </div>
          <div className="src-field">
            <label htmlFor="key-expiry">Expires</label>
            <select id="key-expiry" value={expiry} onChange={(e) => setExpiry(Number(e.target.value))}>
              {EXPIRY.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>
          <div className="src-field src-field--action">
            <button className="src-connect" type="submit" disabled={busy || !name.trim()}>
              {busy ? "Creating…" : "Create key"}
            </button>
          </div>
        </form>

        {error && <div className="dq-error">{error}</div>}

        <div className="section-title" style={{ marginTop: 18 }}>Active keys</div>
        {active.length === 0 ? (
          <div className="access-empty">No keys yet.</div>
        ) : (
          <table className="key-table">
            <thead>
              <tr><th>Name</th><th>Key</th><th>Access</th><th>Created</th><th>Last used</th><th>Expires</th><th><span className="visually-hidden">Actions</span></th></tr>
            </thead>
            <tbody>
              {active.map((k) => (
                <tr key={k.key_id}>
                  <td>{k.name}<div className="key-table__by">{k.created_by_email}</div></td>
                  <td><code>{k.hint}</code></td>
                  <td>{k.role === "editor" ? "Read & write" : "Read"}</td>
                  <td>{day(k.created_at)}</td>
                  <td>{day(k.last_used_at) || "Never"}</td>
                  <td>{day(k.expires_at) || "Never"}</td>
                  <td className="src-row-actions">
                    <button className={`src-remove${confirming === k.key_id ? " is-confirming" : ""}`}
                      onClick={() => revoke(k)} onBlur={() => setConfirming(null)}
                      aria-label={confirming === k.key_id ? `Confirm revoking ${k.name}` : `Revoke ${k.name}`}>
                      {confirming === k.key_id ? "Confirm revoke" : "Revoke"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
