import { useState } from "react";
import { ask } from "../api";
import DataChat from "./DataChat";

const SUGGESTIONS = [
  "What are the key figures in my data?",
  "Summarize the main points of the uploaded documents.",
  "What does the policy say about refunds?",
];

function AnswerCard({ answer }) {
  if (answer.abstained) {
    return (
      <div className="answer answer--abstained">
        <div className="answer__badge answer__badge--abstain">Abstained — not enough evidence</div>
        <p className="answer__reason">{answer.abstention_reason}</p>
        <div className="answer__note">
          The assistant does not guess. When the data can’t support a confident answer, it says so.
        </div>
      </div>
    );
  }
  return (
    <div className="answer">
      <div className="answer__badge">
        Grounded answer · confidence: {answer.confidence} · mode: {answer.mode.toUpperCase()}
      </div>
      <ul className="answer__claims">
        {answer.claims.map((c, i) => (
          <li key={i}>
            <span className="answer__text">{c.text}</span>
            <span className="answer__cite">cited from: {c.evidence.join(", ")}</span>
          </li>
        ))}
      </ul>
      {(answer.claims_removed_by_verifier > 0 || answer.claims_removed_by_number_gate > 0) && (
        <div className="answer__note">
          {answer.claims_removed_by_number_gate + answer.claims_removed_by_verifier} claim(s) were removed by
          the validation gates (unsupported or invented numbers).
        </div>
      )}
    </div>
  );
}

function DocumentsChat() {
  const [question, setQuestion] = useState("");
  const [history, setHistory] = useState([]);
  const [busy, setBusy] = useState(false);

  const submit = async (q) => {
    const text = (q ?? question).trim();
    if (!text || busy) return;
    setBusy(true);
    setQuestion("");
    try {
      const answer = await ask(text);
      setHistory((h) => [{ question: text, answer }, ...h]);
    } catch (err) {
      setHistory((h) => [
        { question: text, answer: { abstained: true, abstention_reason: err?.response?.data?.detail || "Request failed", claims: [] } },
        ...h,
      ]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="ask-intro">
        <h2>Ask your documents</h2>
        <p>Ask about your uploaded PDFs and documents. Every answer cites its source, and abstains when the evidence is thin. No number is ever invented.</p>
        <div className="ask-suggestions">
          {SUGGESTIONS.map((s) => (
            <button key={s} onClick={() => submit(s)} disabled={busy}>{s}</button>
          ))}
        </div>
      </div>
      <form className="ask-box" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <input value={question} onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. What does the contract say about renewal?" />
        <button type="submit" disabled={busy || !question.trim()}>{busy ? "Thinking…" : "Ask"}</button>
      </form>
      <div className="ask-history">
        {history.map((entry, i) => (
          <div className="ask-entry" key={i}>
            <div className="ask-question">{entry.question}</div>
            <AnswerCard answer={entry.answer} />
          </div>
        ))}
      </div>
    </>
  );
}

export default function AskView({ datasetId, hasStructured }) {
  const [mode, setMode] = useState(hasStructured ? "data" : "documents");

  return (
    <div className="ask-view">
      <div className="ask-mode">
        <button className={mode === "data" ? "active" : ""} onClick={() => setMode("data")}>Data (numbers)</button>
        <button className={mode === "documents" ? "active" : ""} onClick={() => setMode("documents")}>Documents</button>
      </div>
      {mode === "data" ? <DataChat datasetId={datasetId} /> : <DocumentsChat />}
    </div>
  );
}
