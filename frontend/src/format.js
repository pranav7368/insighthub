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
