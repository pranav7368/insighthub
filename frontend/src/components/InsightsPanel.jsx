const ICON = { good: "✓", warning: "!", critical: "✕", info: "i" };

export default function InsightsPanel({ insights }) {
  if (!insights?.length) return null;
  return (
    <div className="insights">
      <div className="insights__title">
        Key insights <span className="insights__auto">auto-generated from your data</span>
      </div>
      <div className="insights__list">
        {insights.map((it, i) => (
          <div className={`insight insight--${it.severity}`} key={i}>
            <span className={`insight__icon insight__icon--${it.severity}`}>{ICON[it.severity] || "i"}</span>
            <div className="insight__body">
              <div className="insight__title">{it.title}</div>
              <div className="insight__detail">{it.detail}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
