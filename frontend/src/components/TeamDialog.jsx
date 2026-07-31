import { useEffect, useState } from "react";
import { addMember, changePassword, deleteMember, errorText, listMembers, updateMemberRole } from "../api";

const ROLES = [
  { value: "admin", label: "Admin — full control + team" },
  { value: "editor", label: "Editor — can edit data & dashboards" },
  { value: "viewer", label: "Viewer — read-only" },
];
const ROLE_SHORT = { admin: "Admin", editor: "Editor", viewer: "Viewer" };

export default function TeamDialog({ onClose }) {
  const [members, setMembers] = useState([]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("viewer");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [invited, setInvited] = useState(null);   // {email, temp_password}
  const [pw, setPw] = useState({ open: false, old: "", next: "", note: null });

  const load = () => listMembers().then(setMembers).catch(() => setMembers([]));
  useEffect(() => { load(); }, []);

  const invite = async (e) => {
    e.preventDefault();
    if (!email.trim()) { setError("Enter an email."); return; }
    setBusy(true); setError(null); setInvited(null);
    try {
      const m = await addMember(email.trim(), role, password.trim() || undefined);
      setEmail(""); setPassword("");
      if (m.temp_password) setInvited({ email: m.email, temp_password: m.temp_password });
      load();
    } catch (err) {
      setError(errorText(err, "Could not add the member."));
    } finally {
      setBusy(false);
    }
  };

  const changeRole = async (m, newRole) => {
    setError(null);
    try { await updateMemberRole(m.user_id, newRole); load(); }
    catch (err) { setError(errorText(err, "Could not change the role.")); }
  };
  const remove = async (m) => {
    setError(null);
    try { await deleteMember(m.user_id); load(); }
    catch (err) { setError(errorText(err, "Could not remove the member.")); }
  };

  const submitPw = async (e) => {
    e.preventDefault();
    try {
      await changePassword(pw.old, pw.next);
      setPw({ open: false, old: "", next: "", note: null });
      setError(null);
      alert("Password changed.");
    } catch (err) {
      setPw((p) => ({ ...p, note: errorText(err, "Could not change password.") }));
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal--wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal__header">
          <h3>Team</h3>
          <button onClick={onClose}>Close</button>
        </div>
        <p className="modal__hint">
          Invite teammates and set what they can do. <b>Admins</b> manage the team, <b>editors</b> can
          change data and dashboards, <b>viewers</b> are read-only.
        </p>

        <form className="src-form" onSubmit={invite}>
          <div className="src-field src-field--grow">
            <label>Email</label>
            <input type="email" value={email} placeholder="teammate@company.com"
              onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="src-field">
            <label>Role</label>
            <select value={role} onChange={(e) => setRole(e.target.value)}>
              {ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
            </select>
          </div>
          <div className="src-field src-field--grow">
            <label>Password (optional)</label>
            <input value={password} placeholder="leave blank to auto-generate"
              onChange={(e) => setPassword(e.target.value)} />
          </div>
          <div className="src-field src-field--action">
            <button className="src-connect" type="submit" disabled={busy}>
              {busy ? "Adding…" : "Add member"}
            </button>
          </div>
        </form>

        {invited && (
          <div className="team-invited">
            Added <b>{invited.email}</b>. Share this one-time password so they can log in and change it:
            <code className="team-temp">{invited.temp_password}</code>
          </div>
        )}
        {error && <div className="dq-error">{error}</div>}

        <table className="schema-table" style={{ marginTop: 12 }}>
          <thead><tr><th>Email</th><th>Role</th><th /></tr></thead>
          <tbody>
            {members.map((m) => (
              <tr key={m.user_id}>
                <td>{m.email}</td>
                <td>
                  <select value={m.role} onChange={(e) => changeRole(m, e.target.value)}>
                    {ROLES.map((r) => <option key={r.value} value={r.value}>{ROLE_SHORT[r.value]}</option>)}
                  </select>
                </td>
                <td><button className="src-remove" onClick={() => remove(m)}>Remove</button></td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="section-title" style={{ marginTop: 18 }}>
          <button className="views-btn" onClick={() => setPw((p) => ({ ...p, open: !p.open }))}>
            Change my password
          </button>
        </div>
        {pw.open && (
          <form className="team-pw" onSubmit={submitPw}>
            <input type="password" placeholder="Current password" value={pw.old}
              onChange={(e) => setPw((p) => ({ ...p, old: e.target.value }))} />
            <input type="password" placeholder="New password (min 8)" value={pw.next}
              onChange={(e) => setPw((p) => ({ ...p, next: e.target.value }))} />
            <button className="src-connect" type="submit">Update</button>
            {pw.note && <span className="dq-error">{pw.note}</span>}
          </form>
        )}
      </div>
    </div>
  );
}
