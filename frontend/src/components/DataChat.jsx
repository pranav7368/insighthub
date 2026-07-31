import { useState } from "react";
import { errorText, queryData } from "../api";
import ResultChart from "./ResultChart";

function ComputedFrom({ result }) {
  const [showSql, setShowSql] = useState(false);
  return (
    <div className="dq-query">
      <div className="dq-query__line">
        how this was computed: <code>{result.query}</code>
        {result.sql && (
          <button className="dq-sqltoggle" onClick={() => setShowSql((s) => !s)}>
            {showSql ? "Hide SQL" : "Verify — show SQL"}
          </button>
        )}
      </div>
      {showSql && result.sql && <pre className="dq-sql">{result.sql}</pre>}
    </div>
  );
}

const SUGGESTIONS = [
  "What is the total revenue?",
  "Show revenue by branch",
  "How has revenue changed over time?",
  "Which business unit has the highest profit?",
];

function ResultCard({ entry }) {
  const { result, error } = entry;
  if (error) {
    return (
      <div className="dq-answer dq-answer--error">
        <div className="dq-badge dq-badge--error">Couldn’t answer</div>
        <p className="dq-summary">{error}</p>
      </div>
    );
  }
  return (
    <div className="dq-answer">
      <div className="dq-badge">Answered from your data · computed, not guessed</div>
      <p className="dq-summary">{result.answer}</p>
      <ResultChart result={result} />
      <ComputedFrom result={result} />
    </div>
  );
}

export default function DataChat({ datasetId }) {
  const [question, setQuestion] = useState("");
  const [history, setHistory] = useState([]);
  const [busy, setBusy] = useState(false);

  const submit = async (q) => {
    const text = (q ?? question).trim();
    if (!text || busy || !datasetId) return;
    setBusy(true);
    setQuestion("");
    try {
      const result = await queryData(datasetId, text);
      setHistory((h) => [{ question: text, result }, ...h]);
    } catch (err) {
      setHistory((h) => [{ question: text, error: errorText(err, "Request failed") }, ...h]);
    } finally {
      setBusy(false);
    }
  };

  if (!datasetId) {
    return (
      <div className="empty-panel">
        Upload a CSV or Excel file first — then you can ask questions about the numbers here.
      </div>
    );
  }

  return (
    <>
      <div className="ask-intro">
        <h2>Chat with your data</h2>
        <p>Ask about your numbers in plain English. The assistant turns your question into a query and answers from the actual data — every figure is computed, never invented.</p>
        <div className="ask-suggestions">
          {SUGGESTIONS.map((s) => (
            <button key={s} onClick={() => submit(s)} disabled={busy}>{s}</button>
          ))}
        </div>
      </div>

      <form className="ask-box" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <input value={question} onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. Which branch grew the most? · Average profit by business unit" />
        <button type="submit" disabled={busy || !question.trim()}>{busy ? "Thinking…" : "Ask"}</button>
      </form>

      <div className="ask-history">
        {history.map((entry, i) => (
          <div className="ask-entry" key={i}>
            <div className="ask-question">{entry.question}</div>
            <ResultCard entry={entry} />
          </div>
        ))}
      </div>
    </>
  );
}
