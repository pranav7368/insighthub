import { useEffect, useState } from "react";
import { errorText, listTemplates, loadTemplate } from "../api";

/**
 * Industry templates: pick a business you look like and get a working
 * dashboard in one click — realistic data, the certified metrics that industry
 * reports on, and a saved view arranged to tell that story.
 *
 * Rendered inline on the empty state (a new workspace's first screen) and as a
 * modal from the header once data already exists.
 */
export default function TemplateGallery({ onLoaded, onClose, compact = false }) {
  const [templates, setTemplates] = useState([]);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    listTemplates().then(setTemplates).catch(() => setError("Could not load the template list."));
  }, []);

  const pick = async (template) => {
    setBusy(template.id);
    setError(null);
    try {
      const res = await loadTemplate(template.id);
      await onLoaded(res.dataset_id);
      onClose?.();
    } catch (err) {
      setError(errorText(err, "Could not load that template."));
    } finally {
      setBusy(null);
    }
  };

  const grid = (
    <>
      {error && <div className="tpl-error">{error}</div>}
      <div className={`tpl-grid${compact ? " tpl-grid--compact" : ""}`}>
        {templates.map((t) => (
          <button
            key={t.id} type="button" className="tpl-card"
            onClick={() => pick(t)} disabled={Boolean(busy)}
            aria-busy={busy === t.id}
          >
            <span className="tpl-card__icon" aria-hidden>{t.icon}</span>
            <span className="tpl-card__industry">{t.industry}</span>
            <span className="tpl-card__label">{t.label}</span>
            <span className="tpl-card__desc">{t.description}</span>
            <span className="tpl-card__chips">
              {t.highlights.map((h) => <span key={h} className="tpl-chip">{h}</span>)}
            </span>
            <span className="tpl-card__metrics">
              {t.metrics.length} certified metrics · {busy === t.id ? "Building…" : "Use this template"}
            </span>
          </button>
        ))}
      </div>
    </>
  );

  if (!onClose) return <div className="tpl-inline">{grid}</div>;

  return (
    <div className="modal-backdrop" onClick={busy ? undefined : onClose}>
      <div className="modal modal--wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal__header">
          <h3>Start from an industry template</h3>
          <button onClick={onClose} disabled={Boolean(busy)}>Close</button>
        </div>
        <p className="modal__hint">
          Each template loads a realistic dataset plus the certified metrics and dashboard
          arrangement that industry actually reports on — every figure still computed from the
          data, with the SQL on show.
        </p>
        {grid}
      </div>
    </div>
  );
}
