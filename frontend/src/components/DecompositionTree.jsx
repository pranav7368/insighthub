import { useEffect, useState } from "react";
import { errorText, getVariance } from "../api";
import { formatNumber, humanLabel } from "../format";
import { pctText } from "../drill";

const signed = (v, subtype) => `${v >= 0 ? "+" : "−"}${formatNumber(Math.abs(v), subtype)}`;

/**
 * Decomposition tree: the latest period's change, split level by level. Each
 * column splits the node selected in the previous one — by the dimension that
 * best explains its move (auto), or one the user picks. Every level
 * reconciles: a column's deltas add up to its parent's.
 */
function Column({ datasetId, slice, level, onPick, selected, onDimension }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const key = JSON.stringify([datasetId, slice, level.dimension]);

  useEffect(() => {
    let live = true;
    setError(null);
    getVariance(datasetId, slice, { dimension: level.dimension || undefined, limit: 10 })
      .then((d) => { if (live) setData(d); })
      .catch((e) => { if (live) setError(errorText(e, "Could not split this further.")); });
    return () => { live = false; };
    // slice is captured through key
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  if (error) return <div className="dtree__col"><div className="dtree__empty">{error}</div></div>;
  if (!data) return <div className="dtree__col"><div className="skeleton skeleton--list" aria-busy="true" aria-label="Loading split" /></div>;
  if (!data.dimension) return <div className="dtree__col"><div className="dtree__empty">Nothing left to split by.</div></div>;

  const sub = data.subtype;
  const items = [...data.steps];
  const max = Math.max(1, ...items.map((s) => Math.abs(s.delta)), Math.abs(data.other?.delta || 0));
  return (
    <div className="dtree__col">
      <label className="dtree__dim">
        <span className="visually-hidden">Split by</span>
        <select className="insp-select" value={level.dimension || ""} onChange={(e) => onDimension(e.target.value || null)}>
          <option value="">✦ Auto: {humanLabel(data.auto_dimension || "")}</option>
          {data.ranking.map((r) => <option key={r.dimension} value={r.dimension}>{humanLabel(r.dimension)}</option>)}
        </select>
      </label>
      <ul className="dtree__list">
        {items.map((s) => {
          const name = s.blank ? "(blank)" : String(s.name);
          const on = !s.blank && selected === String(s.name);
          return (
            <li key={name}>
              <button className={`dtree__node${on ? " is-on" : ""}`} disabled={s.blank} aria-pressed={on}
                onClick={() => onPick(data.dimension, String(s.name))}>
                <span className="dtree__name">{name}</span>
                <span className="dtree__value">{formatNumber(s.b, sub)}</span>
                <span className={`dtree__delta delta--${s.delta >= 0 ? "up" : "down"}`}>{signed(s.delta, sub)}</span>
                <span className="dtree__bar" aria-hidden>
                  <span className={`dtree__bar-fill dtree__bar-fill--${s.delta >= 0 ? "up" : "down"}`}
                    style={{ width: `${(Math.abs(s.delta) / max) * 100}%` }} />
                </span>
              </button>
            </li>
          );
        })}
        {data.other && (
          <li className="dtree__node dtree__node--static">
            <span className="dtree__name">Other ({data.other.count})</span>
            <span className="dtree__value">{formatNumber(data.other.b, sub)}</span>
            <span className={`dtree__delta delta--${data.other.delta >= 0 ? "up" : "down"}`}>{signed(data.other.delta, sub)}</span>
          </li>
        )}
      </ul>
    </div>
  );
}

export default function DecompositionTree({ datasetId, measure, subtype, filters, dateFrom, dateTo, onInspect }) {
  const [compare, setCompare] = useState("previous");
  const [levels, setLevels] = useState([{ dimension: null, selected: null }]);
  const [root, setRoot] = useState(null);
  const [error, setError] = useState(null);
  const base = { measure, agg: "sum", filters, date_from: dateFrom || null, date_to: dateTo || null, grain: "month", compare };
  const baseKey = JSON.stringify(base);

  // a new measure / filter / period starts the tree over
  useEffect(() => { setLevels([{ dimension: null, selected: null }]); }, [baseKey]);
  useEffect(() => {
    let live = true;
    setError(null);
    getVariance(datasetId, base, { limit: 1 })
      .then((d) => { if (live) setRoot(d); })
      .catch((e) => { if (live) setError(errorText(e, "Could not build the tree.")); });
    return () => { live = false; };
    // base is captured through baseKey
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetId, baseKey]);

  if (!measure) return null;
  if (error) return null;   // e.g. no date column — the tree has nothing to show

  // the slice each column splits: base filters + every selection to its left
  const sliceAt = (i) => {
    const f = { ...filters };
    for (let j = 0; j < i; j++) {
      const l = levels[j];
      if (l.selected != null && l.dimension_used) f[l.dimension_used] = l.selected;
    }
    return { ...base, filters: f };
  };
  const pick = (i, dim, value) => setLevels((ls) => {
    const next = ls.slice(0, i + 1);
    next[i] = { ...next[i], selected: next[i].selected === value ? null : value, dimension_used: dim };
    if (next[i].selected != null) next.push({ dimension: null, selected: null });
    return next;
  });
  const setDim = (i, dim) => setLevels((ls) => [...ls.slice(0, i), { dimension: dim, selected: null }]);
  const deepest = sliceAt(levels.length);
  const path = Object.entries(deepest.filters).filter(([k]) => !(k in (filters || {})));

  return (
    <div className="chart-card dtree">
      <div className="chart-card__title">
        Decomposition tree — {humanLabel(measure)}
        {root && <span className="chart-card__tag">{root.b.label} vs {root.a.label}</span>}
        <div className="seg dtree__compare" role="group" aria-label="Compare with">
          {[["previous", "vs previous month"], ["year_ago", "vs a year ago"]].map(([k, label]) => (
            <button key={k} aria-pressed={compare === k} className={compare === k ? "is-on" : ""}
              onClick={() => setCompare(k)}>{label}</button>
          ))}
        </div>
      </div>
      {root && (
        <div className="dtree__scroll" tabIndex={0} role="region" aria-label="Decomposition tree">
          <div className="dtree__cols">
            <div className="dtree__col dtree__col--root">
              <div className="dtree__rootlabel">{humanLabel(measure)}</div>
              <div className="dtree__rootvalue">{formatNumber(root.b.value, subtype)}</div>
              <div className={`dtree__delta delta--${root.delta >= 0 ? "up" : "down"}`}>
                {signed(root.delta, subtype)} {pctText(root.pct) ? `(${pctText(root.pct)})` : ""}
              </div>
              <div className="insp-caption">{root.a.label}: {formatNumber(root.a.value, subtype)}</div>
              {root.like_for_like && <div className="insp-caption">like-for-like days</div>}
            </div>
            {levels.map((l, i) => (
              <Column key={`${i}-${JSON.stringify(sliceAt(i).filters)}`} datasetId={datasetId} slice={sliceAt(i)} level={l}
                selected={l.selected} onPick={(dim, v) => pick(i, dim, v)} onDimension={(d) => setDim(i, d)} />
            ))}
          </div>
        </div>
      )}
      <div className="dtree__foot">
        <span className="insp-caption">
          {path.length ? `Path: ${path.map(([k, v]) => `${humanLabel(k)} ${v}`).join(" › ")}` : "Click a bar to split it further."}
        </span>
        {onInspect && (
          <button className="views-btn no-export" onClick={() => onInspect({ filters: deepest.filters, tab: "change", compare })}>
            Open in details ›
          </button>
        )}
      </div>
    </div>
  );
}
