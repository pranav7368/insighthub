import { useCallback, useEffect, useMemo, useState } from "react";
import { getDashboard } from "../api";
import ComparisonChart from "./ComparisonChart";
import { formatNumber, humanLabel } from "../format";

function deltaPct(a, b) {
  if (b === 0 || b == null || a == null) return null;
  return Math.round((a - b) / Math.abs(b) * 1000) / 10;
}

export default function ComparePane({ datasetId }) {
  const [base, setBase] = useState(null);
  const [mode, setMode] = useState("segment");
  const [dimension, setDimension] = useState(null);
  const [valA, setValA] = useState("");
  const [valB, setValB] = useState("");
  const [pa, setPa] = useState({ from: "", to: "" });
  const [pb, setPb] = useState({ from: "", to: "" });
  const [measure, setMeasure] = useState(null);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    setBase(null); setResult(null); setDimension(null); setMeasure(null);
    getDashboard(datasetId, {}).then((d) => {
      setBase(d);
      const dims = Object.keys(d.filter_options || {});
      if (dims.length) setDimension(dims[0]);
      if (d.chosen_measure) setMeasure(d.chosen_measure);
    }).catch(() => setError("Could not load dataset options."));
  }, [datasetId]);

  const dims = base ? Object.entries(base.filter_options || {}) : [];
  const measures = base ? base.kpis.map((k) => ({ name: k.column, subtype: k.subtype })) : [];
  const dimValues = base && dimension ? base.filter_options[dimension]?.values || [] : [];

  const run = useCallback(async () => {
    setBusy(true); setError(null);
    try {
      let fa = {}, fb = {}, labelA, labelB;
      if (mode === "segment") {
        if (!dimension || !valA || !valB) { setError("Pick a dimension and two values."); setBusy(false); return; }
        fa = { [dimension]: valA }; fb = { [dimension]: valB };
        labelA = valA; labelB = valB;
      } else {
        if (!pa.from || !pb.from) { setError("Pick both periods."); setBusy(false); return; }
        fa = { date_from: pa.from, date_to: pa.to || pa.from };
        fb = { date_from: pb.from, date_to: pb.to || pb.from };
        labelA = `${pa.from}…${pa.to || pa.from}`;
        labelB = `${pb.from}…${pb.to || pb.from}`;
      }
      const [a, b] = await Promise.all([getDashboard(datasetId, fa), getDashboard(datasetId, fb)]);
      setResult({ a, b, labelA, labelB });
    } catch (e) {
      setError(e?.response?.data?.detail || "Comparison failed.");
    } finally {
      setBusy(false);
    }
  }, [mode, dimension, valA, valB, pa, pb, datasetId]);

  const overlay = useMemo(() => {
    if (!result || mode !== "segment" || !measure) return null;
    const byPeriod = {};
    (result.a.trend || []).forEach((r) => { byPeriod[r.period] = { period: r.period, a: r[measure] }; });
    (result.b.trend || []).forEach((r) => { byPeriod[r.period] = { ...(byPeriod[r.period] || { period: r.period }), b: r[measure] }; });
    return Object.values(byPeriod).sort((x, y) => x.period.localeCompare(y.period));
  }, [result, mode, measure]);

  if (!base) return <div className="empty-panel">{error || "Loading…"}</div>;

  return (
    <div className="compare-pane">
      <h2>Compare</h2>
      <div className="compare-controls">
        <div className="ask-mode">
          <button className={mode === "segment" ? "active" : ""} onClick={() => { setMode("segment"); setResult(null); }}>By segment</button>
          <button className={mode === "period" ? "active" : ""} onClick={() => { setMode("period"); setResult(null); }}>By period</button>
        </div>

        {mode === "segment" ? (
          <div className="compare-fields">
            <label>Dimension
              <select value={dimension || ""} onChange={(e) => { setDimension(e.target.value); setValA(""); setValB(""); }}>
                {dims.map(([name]) => <option key={name} value={name}>{humanLabel(name)}</option>)}
              </select>
            </label>
            <label>A
              <select value={valA} onChange={(e) => setValA(e.target.value)}>
                <option value="">choose…</option>
                {dimValues.map((v) => <option key={v} value={v}>{v}</option>)}
              </select>
            </label>
            <span className="compare-vs">vs</span>
            <label>B
              <select value={valB} onChange={(e) => setValB(e.target.value)}>
                <option value="">choose…</option>
                {dimValues.map((v) => <option key={v} value={v}>{v}</option>)}
              </select>
            </label>
          </div>
        ) : (
          <div className="compare-fields">
            <label>Period A from<input type="month" value={pa.from} onChange={(e) => setPa({ ...pa, from: e.target.value })} /></label>
            <label>to<input type="month" value={pa.to} onChange={(e) => setPa({ ...pa, to: e.target.value })} /></label>
            <span className="compare-vs">vs</span>
            <label>Period B from<input type="month" value={pb.from} onChange={(e) => setPb({ ...pb, from: e.target.value })} /></label>
            <label>to<input type="month" value={pb.to} onChange={(e) => setPb({ ...pb, to: e.target.value })} /></label>
          </div>
        )}

        {measures.length > 1 && (
          <label className="compare-measure">Chart measure
            <select value={measure || ""} onChange={(e) => setMeasure(e.target.value)}>
              {measures.map((m) => <option key={m.name} value={m.name}>{humanLabel(m.name)}</option>)}
            </select>
          </label>
        )}

        <button className="compare-run" onClick={run} disabled={busy}>{busy ? "Comparing…" : "Compare"}</button>
      </div>

      {error && <div className="empty-panel">{error}</div>}

      {result && (
        <>
          <div className="compare-kpis">
            <div className="compare-kpis__head">
              <span />
              <span className="compare-col compare-col--a">{result.labelA}</span>
              <span className="compare-col compare-col--b">{result.labelB}</span>
              <span className="compare-col">A vs B</span>
            </div>
            {measures.map((m) => {
              const av = result.a.kpis.find((k) => k.column === m.name)?.total;
              const bv = result.b.kpis.find((k) => k.column === m.name)?.total;
              const d = deltaPct(av, bv);
              return (
                <div className="compare-kpis__row" key={m.name}>
                  <span className="compare-kpis__label">{humanLabel(m.name)}</span>
                  <span className="compare-col">{formatNumber(av, m.subtype)}</span>
                  <span className="compare-col">{formatNumber(bv, m.subtype)}</span>
                  <span className={`compare-col compare-delta ${d == null ? "" : d > 0 ? "up" : d < 0 ? "down" : "flat"}`}>
                    {d == null ? "—" : `${d > 0 ? "▲" : d < 0 ? "▼" : "▬"} ${Math.abs(d)}%`}
                  </span>
                </div>
              );
            })}
          </div>

          {overlay && overlay.length > 1 && (
            <ComparisonChart data={overlay} measure={measure}
              subtype={measures.find((m) => m.name === measure)?.subtype}
              labelA={result.labelA} labelB={result.labelB} />
          )}
        </>
      )}
    </div>
  );
}
