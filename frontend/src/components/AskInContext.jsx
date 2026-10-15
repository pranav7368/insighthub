import { useState } from "react";
import { errorText, queryData } from "../api";
import { humanLabel } from "../format";
import ResultChart from "./ResultChart";

/**
 * A question asked from inside a drill is answered inside it: from
 * "Region: North, Nov 2025", "revenue by product" means North's November
 * revenue by product. Same grounded engine as the Ask tab — the answer is a
 * validated query, shown with its SQL.
 */
export default function AskInContext({ datasetId, ctx }) {
  const [question, setQuestion] = useState("");
  const [answers, setAnswers] = useState([]);
  const [busy, setBusy] = useState(false);
  const scope = [
    ...Object.entries(ctx.filters || {}).map(([k, v]) => `${humanLabel(k)}: ${v}`),
    ...(ctx.date_from || ctx.date_to ? [`${ctx.date_from || "…"} → ${ctx.date_to || "…"}`] : []),
  ];
  const measure = humanLabel(ctx.measure || "revenue").toLowerCase();
  const suggestions = [`${measure} by month`, `top 5 by ${measure}`, `average ${measure}`];

  const ask = async (text) => {
    const q = (text ?? question).trim();
    if (!q) return;
    setBusy(true);
    setQuestion("");
    try {
      const result = await queryData(datasetId, q,
        { filters: ctx.filters || {}, date_from: ctx.date_from || null, date_to: ctx.date_to || null });
      setAnswers((a) => [{ q, result }, ...a]);
    } catch (err) {
      setAnswers((a) => [{ q, error: errorText(err, "Could not answer that.") }, ...a]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="insp-block">
      <h3>Ask about this</h3>
      <p className="insp-caption">
        {scope.length ? <>Answers stay inside <b>{scope.join(" · ")}</b>.</> : "Answers cover every row you can access."}
        {" "}Every number comes from a query you can inspect.
      </p>
      <form className="ask-ctx" onSubmit={(e) => { e.preventDefault(); ask(); }}>
        <input className="insp-input" value={question} onChange={(e) => setQuestion(e.target.value)}
          placeholder={`e.g. ${suggestions[0]}`} aria-label="Question about this slice" />
        <button className="views-btn views-btn--accent" disabled={busy || !question.trim()}>{busy ? "…" : "Ask"}</button>
      </form>
      {answers.length === 0 && (
        <div className="ask-ctx__suggest">
          {suggestions.map((s) => <button key={s} className="chip-btn" onClick={() => ask(s)}>{s}</button>)}
        </div>
      )}
      {answers.map((a, i) => (
        <div key={answers.length - i} className="ask-ctx__answer">
          <div className="ask-ctx__q">{a.q}</div>
          {a.error ? <p className="form-error">{a.error}</p> : (
            <>
              <p className="insp-explain">{a.result.answer}</p>
              <ResultChart result={a.result} />
              <details className="ask-ctx__sql">
                <summary>How this was computed: {a.result.query}</summary>
                <pre className="sql-block"><code>{a.result.sql}</code></pre>
              </details>
            </>
          )}
        </div>
      ))}
    </section>
  );
}
