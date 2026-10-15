// Quick date-range presets computed from the dataset's own latest date.
// Emit day-format (YYYY-MM-DD) so they display in the date inputs; `to` is the
// dataset's latest date, so "MTD" means "this month, as far as the data goes".
//
// Dates are handled as calendar parts, never through Date#toISOString: that
// converts to UTC, and east of Greenwich (IST is +5:30) local midnight on the
// 1st becomes the previous day — every preset used to start a day early.
const pad = (n) => String(n).padStart(2, "0");

export function presetFrom(latestIso, preset) {
  const [y, m] = latestIso.slice(0, 10).split("-").map(Number);
  const back = (months) => {
    const idx = y * 12 + (m - 1) - months;
    return `${Math.floor(idx / 12)}-${pad((idx % 12) + 1)}-01`;
  };
  switch (preset) {
    case "MTD": return back(0);
    case "QTD": return `${y}-${pad(Math.floor((m - 1) / 3) * 3 + 1)}-01`;
    case "YTD": return `${y}-01-01`;
    case "3M": return back(2);
    case "6M": return back(5);
    case "12M": return back(11);
    default: return null;
  }
}

