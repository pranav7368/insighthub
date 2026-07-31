export default function DataProfile({ profile }) {
  if (!profile) return null;
  const { rows, columns_used, completeness_pct, date_span } = profile;
  return (
    <div className="data-profile">
      <span><b>{rows?.toLocaleString("en-IN")}</b> rows</span>
      <span><b>{columns_used}</b> fields analysed</span>
      {completeness_pct != null && <span><b>{completeness_pct}%</b> complete</span>}
      {date_span && <span>{date_span.from} → {date_span.to}</span>}
    </div>
  );
}
