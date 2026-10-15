import { useEffect, useState } from "react";

/**
 * The saved-view switcher: the picker plus the one action you most often want
 * next (save this view, or update it when it has changed). Less frequent view
 * actions — set default, delete, arrange, show/hide sections — live in the
 * toolbar's "⋯" menu, so the toolbar stays one calm line.
 */
// `nameRequest`: bump it to open the name field from elsewhere ("Save as…" in the ⋯ menu)
export default function ViewsBar({ views, activeViewId, dirty, onApply, onSave, onUpdate, nameRequest = 0 }) {
  const [naming, setNaming] = useState(false);
  useEffect(() => { if (nameRequest) setNaming(true); }, [nameRequest]);
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
        className="tb-select"
        aria-label="Saved view"
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

      {active && dirty && <button className="tb-btn tb-btn--accent" onClick={onUpdate}>Update view</button>}
      {!active && !naming && <button className="tb-btn" onClick={() => setNaming(true)}>Save view</button>}

      {naming && (
        <form className="views-name" onSubmit={submitName}>
          <input autoFocus value={name} placeholder="View name" aria-label="View name"
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Escape") setNaming(false); }} />
          <button className="tb-btn tb-btn--accent" type="submit">Save</button>
        </form>
      )}
    </div>
  );
}

