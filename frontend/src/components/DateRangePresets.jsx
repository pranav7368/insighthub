import { presetFrom } from "../dates";

const PRESETS = [
  { label: "MTD", title: "Month to date" },
  { label: "QTD", title: "Quarter to date" },
  { label: "YTD", title: "Year to date" },
  { label: "3M", title: "Last 3 months" },
  { label: "6M", title: "Last 6 months" },
  { label: "12M", title: "Last 12 months" },
];

export default function DateRangePresets({ dateSpan, activeFrom, onApply, onClear }) {
  if (!dateSpan?.to) return null;
  const toDate = dateSpan.to.slice(0, 10);
  // two presets can resolve to the same start (YTD in January = MTD); light the first
  let lit = false;
  return (
    <div className="date-presets" role="group" aria-label="Date range">
      {PRESETS.map((p) => {
        const from = presetFrom(toDate, p.label);
        const active = !lit && activeFrom === from;
        if (active) lit = true;
        return (
          <button key={p.label} className={active ? "active" : ""} title={p.title} aria-pressed={active}
            onClick={() => onApply(from, toDate)}>{p.label}</button>
        );
      })}
      <button className={!activeFrom ? "active" : ""} aria-pressed={!activeFrom} onClick={onClear}>All</button>
    </div>
  );
}
