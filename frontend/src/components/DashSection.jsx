import { useState } from "react";
import { sectionLabel } from "../sections";

/**
 * One dashboard section, wrapped so it can be rearranged.
 *
 * Outside arrange mode this is a plain pass-through wrapper — no drag
 * handlers, nothing intercepting clicks — so chart interactions (click a bar
 * to filter, hover for a tooltip) behave exactly as before. Arrange mode turns
 * on the drag affordances and lifts the charts out of the pointer path.
 */
export default function DashSection({
  sectionKey, arranging, isFirst, isLast,
  onReorder, onMove, onHide, children,
}) {
  const [over, setOver] = useState(false);

  if (!arranging) return <div className="dash-section" data-tour={sectionKey}>{children}</div>;

  const label = sectionLabel(sectionKey);

  return (
    <div
      className={`dash-section dash-section--arranging${over ? " dash-section--over" : ""}`}
      draggable
      onDragStart={(e) => {
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", sectionKey);
      }}
      onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; }}
      onDragEnter={() => setOver(true)}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        const from = e.dataTransfer.getData("text/plain");
        if (from && from !== sectionKey) onReorder(from, sectionKey);
      }}
    >
      <div className="dash-section__bar">
        <span className="dash-section__grip" aria-hidden>⠿</span>
        <span className="dash-section__label">{label}</span>
        <div className="dash-section__tools">
          <button type="button" title={`Move ${label} up`} aria-label={`Move ${label} up`}
            disabled={isFirst} onClick={() => onMove(-1)}>↑</button>
          <button type="button" title={`Move ${label} down`} aria-label={`Move ${label} down`}
            disabled={isLast} onClick={() => onMove(1)}>↓</button>
          <button type="button" className="dash-section__hide"
            title={`Hide ${label}`} aria-label={`Hide ${label}`} onClick={onHide}>Hide</button>
        </div>
      </div>
      <div className="dash-section__body">{children}</div>
    </div>
  );
}
