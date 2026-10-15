export function formatNumber(value, subtype) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const n = Number(value);
  if (subtype === "percentage") {
    const v = Math.abs(n) <= 1 ? n * 100 : n;
    return `${v.toFixed(1)}%`;
  }
  if (subtype === "currency") {
    if (Math.abs(n) >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
    if (Math.abs(n) >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`;
    return `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
  }
  return n.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

export function humanLabel(name) {
  return String(name).replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// ------------------------------------------------------------ dates ---
// Human dates from the API's ISO strings. Parsed as calendar parts, never via
// Date + toISOString, so a timezone can never move a day.
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-10-28" -> "28 Oct 2026"; "2026-10" -> "Oct 2026"; "2026-Q4" / "2026" pass through. */
export function formatDate(iso) {
  if (!iso) return "";
  const s = String(iso);
  const m = s.match(/^(\d{4})-(\d{2})(?:-(\d{2}))?/);
  if (!m) return s;
  const [, y, mo, d] = m;
  const month = MONTHS[Number(mo) - 1];
  if (!month) return s;
  return d ? `${Number(d)} ${month} ${y}` : `${month} ${y}`;
}

/** Compact axis tick: "Oct 2026" for a month, "28 Oct" for a day. */
export function formatTick(iso) {
  const s = String(iso ?? "");
  if (/^\d{4}-\d{2}-\d{2}/.test(s)) return formatDate(s).replace(/ \d{4}$/, "");
  return formatDate(s);
}

/** A from/to pair as one phrase: "Oct 2026", "1 Jan – 28 Oct 2026", "from Mar 2025". */
export function formatRange(from, to) {
  if (from && to) {
    if (from === to) return formatDate(from);
    const a = formatDate(from), b = formatDate(to);
    const sameYear = String(from).slice(0, 4) === String(to).slice(0, 4);
    return `${sameYear ? a.replace(/ \d{4}$/, "") : a} – ${b}`;
  }
  if (from) return `from ${formatDate(from)}`;
  if (to) return `until ${formatDate(to)}`;
  return "";
}
