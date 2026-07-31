import { useEffect, useState } from "react";
import {
  createRlsRule, deleteRlsRule, errorText, getPrivacy, getSchema,
  listMembers, listRlsRules, setPrivacy,
} from "../api";

const KINDS = [
  ["email", "Email"],
  ["phone", "Phone"],
  ["national_id", "ID number"],
  ["person_name", "Person name"],
];

/**
 * Who can see which rows, and which columns are redacted. Admin-only, because
 * both lists *are* the access policy — reading them tells you what is
 * restricted and what is sensitive.
 */
export default function AccessDialog({ datasetId, datasetName, onClose }) {
  const [members, setMembers] = useState([]);
  const [columns, setColumns] = useState([]);
  const [rules, setRules] = useState([]);
  const [policies, setPolicies] = useState([]);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const [userId, setUserId] = useState("");
  const [column, setColumn] = useState("");
  const [operator, setOperator] = useState("in");
  const [values, setValues] = useState("");

  const load = async () => {
    try {
      const [m, cols, rs, ps] = await Promise.all([
        listMembers(), getSchema(datasetId), listRlsRules(datasetId), getPrivacy(datasetId),
      ]);
      setMembers(m);
      setColumns(cols);
      setRules(rs);
      setPolicies(ps);
    } catch (err) {
      setError(errorText(err, "Could not load the access settings."));
    }
  };

  useEffect(() => { load(); }, [datasetId]);   // eslint-disable-line react-hooks/exhaustive-deps

  const emailFor = (id) => members.find((m) => m.user_id === id)?.email || id;
  const dimensions = columns.filter((c) => c.role === "dimension" || c.role === "ignored");

  const addRule = async (e) => {
    e.preventDefault();
    const list = values.split(",").map((v) => v.trim()).filter(Boolean);
    if (!userId || !column || list.length === 0) {
      setError("Pick a member, a column, and at least one value.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await createRlsRule(datasetId, { user_id: userId, column_name: column,
                                       values: list, operator });
      setValues("");
      await load();
    } catch (err) {
      setError(errorText(err, "Could not add the rule."));
    } finally {
      setBusy(false);
    }
  };

  const removeRule = async (ruleId) => {
    setError(null);
    try { await deleteRlsRule(ruleId); await load(); }
    catch (err) { setError(errorText(err, "Could not remove the rule.")); }
  };

  const toggleMask = async (policy) => {
    setError(null);
    try {
      await setPrivacy(datasetId, {
        column_name: policy.column_name,
        masked: !policy.masked,
        pii_kind: policy.pii_kind,
      });
      await load();
    } catch (err) { setError(errorText(err, "Could not update the column.")); }
  };

  const maskColumn = async (name, kind) => {
    setError(null);
    try {
      await setPrivacy(datasetId, { column_name: name, masked: true, pii_kind: kind });
      await load();
    } catch (err) { setError(errorText(err, "Could not mask the column.")); }
  };

  const unpoliced = columns.filter(
    (c) => !policies.some((p) => p.column_name === c.name)
  );

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal--wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal__header">
          <h3>Access & privacy — {datasetName}</h3>
          <button onClick={onClose}>Close</button>
        </div>
        <p className="modal__hint">
          Restrict which rows a teammate can see, and redact sensitive columns. Both apply
          everywhere at once — dashboards, Ask, exports and share links — and neither changes
          the underlying data, so you can relax them again at any time.
        </p>

        {error && <div className="tpl-error">{error}</div>}

        {/* ---------------------------------------------------- row access -- */}
        <div className="section-title">Row access</div>
        <p className="access-note">
          A member with no rules sees every row. Rules on the same column widen each other;
          rules on different columns narrow.
        </p>

        <form className="access-form" onSubmit={addRule}>
          <select value={userId} onChange={(e) => setUserId(e.target.value)}>
            <option value="">Member…</option>
            {members.map((m) => (
              <option key={m.user_id} value={m.user_id}>{m.email} ({m.role})</option>
            ))}
          </select>
          <select value={column} onChange={(e) => setColumn(e.target.value)}>
            <option value="">Column…</option>
            {dimensions.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
          </select>
          <select value={operator} onChange={(e) => setOperator(e.target.value)}>
            <option value="in">is one of</option>
            <option value="not_in">is not one of</option>
          </select>
          <input value={values} onChange={(e) => setValues(e.target.value)}
            placeholder="North, East" aria-label="Values, comma separated" />
          <button className="views-btn views-btn--accent" type="submit" disabled={busy}>
            {busy ? "Adding…" : "Add rule"}
          </button>
        </form>

        {rules.length === 0 ? (
          <div className="access-empty">No row restrictions — everyone sees all rows.</div>
        ) : (
          <table className="access-table">
            <thead>
              <tr><th>Member</th><th>Rule</th><th /></tr>
            </thead>
            <tbody>
              {rules.map((r) => (
                <tr key={r.rule_id}>
                  <td>{emailFor(r.user_id)}</td>
                  <td>
                    <code>{r.column_name}</code>{" "}
                    {r.operator === "not_in" ? "is not one of" : "is one of"}{" "}
                    <b>{r.values.join(", ")}</b>
                  </td>
                  <td className="access-actions">
                    <button className="src-remove" onClick={() => removeRule(r.rule_id)}>Remove</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {/* ------------------------------------------------ sensitive cols -- */}
        <div className="section-title access-section">Sensitive columns</div>
        <p className="access-note">
          Masked columns are redacted for everyone except admins — including in CSV exports and
          public share links. Detected automatically on upload; adjust anything it got wrong.
        </p>

        {policies.length === 0 ? (
          <div className="access-empty">No sensitive columns detected.</div>
        ) : (
          <table className="access-table">
            <thead>
              <tr><th>Column</th><th>Type</th><th>Visible to</th><th /></tr>
            </thead>
            <tbody>
              {policies.map((p) => (
                <tr key={p.column_name}>
                  <td><code>{p.column_name}</code></td>
                  <td>{KINDS.find(([k]) => k === p.pii_kind)?.[1] || "Sensitive"}</td>
                  <td>
                    <span className={`src-badge ${p.masked ? "src-badge--ok" : "src-badge--pending"}`}>
                      {p.masked ? "Admins only" : "Everyone"}
                    </span>
                  </td>
                  <td className="access-actions">
                    <button onClick={() => toggleMask(p)}>
                      {p.masked ? "Unmask" : "Mask"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {unpoliced.length > 0 && (
          <details className="access-more">
            <summary>Mask another column</summary>
            <div className="access-more__list">
              {unpoliced.map((c) => (
                <div key={c.name} className="access-more__row">
                  <code>{c.name}</code>
                  <select defaultValue="" onChange={(e) => e.target.value && maskColumn(c.name, e.target.value)}>
                    <option value="">Mask as…</option>
                    {KINDS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                  </select>
                </div>
              ))}
            </div>
          </details>
        )}
      </div>
    </div>
  );
}
