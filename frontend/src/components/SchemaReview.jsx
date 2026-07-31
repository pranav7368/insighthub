import { useState } from "react";
import { humanLabel } from "../format";

const ROLES = ["measure", "dimension", "date", "ignored"];
const SUBTYPES = {
  measure: ["currency", "count", "generic"],
  dimension: ["business_unit", "branch", "generic"],
  date: [],
  ignored: [],
};

export default function SchemaReview({ columns, onOverride, onClose }) {
  const [pending, setPending] = useState({});
  const val = (col, field) => pending[col.name]?.[field] ?? col[field];
  const setField = (name, field, value) =>
    setPending((p) => ({ ...p, [name]: { ...p[name], [field]: value } }));

  const save = (col) => {
    const role = val(col, "role");
    const subtype = SUBTYPES[role]?.length ? val(col, "subtype") || SUBTYPES[role][0] : null;
    onOverride(col.name, role, subtype);
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal__header">
          <h3>Detected columns</h3>
          <button onClick={onClose}>Close</button>
        </div>
        <p className="modal__hint">
          Every column was auto-classified. If anything looks wrong, adjust its role or subtype here.
        </p>
        <table className="schema-table">
          <thead>
            <tr><th>Column</th><th>Distinct</th><th>Role</th><th>Subtype</th><th /></tr>
          </thead>
          <tbody>
            {columns.map((col) => {
              const role = val(col, "role");
              const changed = pending[col.name] !== undefined;
              return (
                <tr key={col.name} className={changed ? "schema-row--changed" : ""}>
                  <td>{humanLabel(col.name)}</td>
                  <td>{col.distinct_count}</td>
                  <td>
                    <select value={role} onChange={(e) => setField(col.name, "role", e.target.value)}>
                      {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                    </select>
                  </td>
                  <td>
                    {SUBTYPES[role]?.length ? (
                      <select value={val(col, "subtype") || SUBTYPES[role][0]}
                        onChange={(e) => setField(col.name, "subtype", e.target.value)}>
                        {SUBTYPES[role].map((s) => <option key={s} value={s}>{s}</option>)}
                      </select>
                    ) : "-"}
                  </td>
                  <td>{changed && <button className="schema-save" onClick={() => save(col)}>Save</button>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
