// Quick date-range presets computed from the dataset's own latest date.
// Emit day-format (YYYY-MM-DD) so they display in the date inputs; the `from`
// is aligned to the first of its month, `to` is the dataset's latest date.
function firstOfMonthBack(iso, months) {
  const d = new Date(iso.slice(0, 10) + "T00:00:00");
  d.setDate(1);
  d.setMonth(d.getMonth() - months);
  return d.toISOString().slice(0, 10); // YYYY-MM-DD
}

const PRESETS = [
  { label: "3M", months: 3 },
  { label: "6M", months: 6 },
  { label: "12M", months: 12 },
];

export default function DateRangePresets({ dateSpan, activeFrom, onApply, onClear }) {
  if (!dateSpan?.to) return null;
  const toDate = dateSpan.to.slice(0, 10);
  return (
    <div className="date-presets">
      {PRESETS.map((p) => {
        const from = firstOfMonthBack(dateSpan.to, p.months - 1);
        const active = activeFrom === from;
        return (
          <button key={p.label} className={active ? "active" : ""}
            onClick={() => onApply(from, toDate)}>{p.label}</button>
        );
      })}
      <button className={!activeFrom ? "active" : ""} onClick={onClear}>All</button>
    </div>
  );
}
