import { useState } from "react";
import { SECTIONS } from "../sections";

export default function ViewsBar({
  views, activeViewId, dirty, hiddenSections, arranging,
  onApply, onToggleSection, onSave, onUpdate, onDelete, onSetDefault, onToggleArrange,
}) {
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  const active = views.find((v) => v.view_id === activeViewId) || null;

  const submitName = (e) => {
    e.preventDefault();
    const n = name.trim();
    if (!n) return;
    onSave(n);
    setName("");
    setNaming(false);
  };

  return (
    <div className="views-bar no-export">
      <select
        className="views-select"
        value={activeViewId || ""}
        onChange={(e) => {
          const v = views.find((x) => x.view_id === e.target.value);
          if (v) onApply(v);
        }}
      >
        <option value="">{activeViewId ? "Unsaved view" : "Default view"}</option>
        {views.map((v) => (
          <option key={v.view_id} value={v.view_id}>
            {v.name}{v.is_default ? " ★" : ""}
          </option>
        ))}
      </select>

      {active ? (
        <>
          {dirty && <button className="views-btn views-btn--accent" onClick={onUpdate}>Update</button>}
          <button className="views-btn" onClick={onSetDefault} disabled={active.is_default}
            title="Open this dataset on this view">
            {active.is_default ? "★ Default" : "Set default"}
          </button>
          <button className="views-btn views-btn--danger" onClick={() => onDelete(active)}>Delete</button>
          <button className="views-btn" onClick={() => setNaming((s) => !s)}>Save as…</button>
        </>
      ) : (
        <button className="views-btn views-btn--accent" onClick={() => setNaming((s) => !s)}>Save view</button>
      )}

      {naming && (
        <form className="views-name" onSubmit={submitName}>
          <input autoFocus value={name} placeholder="View name" onChange={(e) => setName(e.target.value)} />
          <button className="views-btn views-btn--accent" type="submit">Save</button>
        </form>
      )}

      <button
        className={`views-btn views-btn--arrange${arranging ? " is-on" : ""}`}
        onClick={onToggleArrange} aria-pressed={arranging}
        title="Drag sections into the order you want"
      >
        <span aria-hidden>⇅</span> {arranging ? "Done" : "Arrange"}
      </button>

      <details className="menu views-customize">
        <summary className="menu__btn">
          Customize{hiddenSections.length > 0 ? ` (${hiddenSections.length} hidden)` : ""} <span aria-hidden>▾</span>
        </summary>
        <div className="menu__list menu__list--checks" role="menu">
          {SECTIONS.map(([key, label]) => (
            <label key={key} className="views-check">
              <input
                type="checkbox"
                checked={!hiddenSections.includes(key)}
                onChange={() => onToggleSection(key)}
              />
              {label}
            </label>
          ))}
        </div>
      </details>
    </div>
  );
}
