import { useEffect, useState } from "react";
import { errorText, getPvm, getVariance } from "../api";
import { formatNumber, humanLabel } from "../format";
import { drillInto, pctText } from "../drill";
import Waterfall from "./Waterfall";

const signed = (v, subtype) => `${v >= 0 ? "+" : "−"}${formatNumber(Math.abs(v), subtype)}`;
const memberLabel = (s) => (s.blank ? "(blank)" : String(s.name));

function useFetch(fn, key) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  useEffect(() => {
    let live = true;
    setState((s) => ({ ...s, loading: true, error: null }));
    fn()
      .then((data) => { if (live) setState({ data, error: null, loading: false }); })
      .catch((e) => { if (live) setState({ data: null, error: errorText(e, "Could not analyse the change."), loading: false }); });
    return () => { live = false; };
    // fn is captured through key
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return state;
}

/** "Is this change real or noise?" — the latest move against how much the
 *  series usually moves from one period to the next. */
export function Significance({ sig, grain, subtype }) {
  const times = `${Math.abs(sig.z).toFixed(1)}×`;
  const typical = `±${formatNumber(sig.typical_change, subtype)}`;
  const text = {
    normal: `Within normal variation — this typically moves ${typical} from one ${grain} to the next.`,
    notable: `A notable move: ${times} the typical ${grain}-to-${grain} swing of ${typical}.`,
    unusual: `Unusual: ${times} the typical ${grain}-to-${grain} swing of ${typical}. Find the cause before acting on it.`,
  }[sig.level];
  return (
    <p className={`signif signif--${sig.level}`}>
      <span className="signif__badge">{sig.level === "normal" ? "Normal" : sig.level === "notable" ? "Notable" : "Unusual"}</span>
      {text}
      <span className="signif__basis">
        {" "}Based on {sig.history} earlier changes{sig.window_days ? `, each over the first ${sig.window_days} days` : ""}.
      </span>
    </p>
  );
}

function PriceVolumeMix({ datasetId, ctx, measures }) {
  const [volume, setVolume] = useState(null);
  const [dimension, setDimension] = useState(null);
  const key = JSON.stringify([datasetId, ctx.measure, ctx.filters, ctx.date_from, ctx.date_to, ctx.grain, ctx.compare, volume, dimension]);
  const { data, error, loading } = useFetch(() => getPvm(datasetId, ctx, { volume, dimension }), key);
  const volumeChoices = measures.filter((m) => m.name !== ctx.measure);

  if (error && !volume) {
    return (
      <section className="insp-block">
        <h3>Price, volume &amp; mix</h3>
        <p className="insp-caption">Is {humanLabel(ctx.measure || "this").toLowerCase()} a quantity times a price? Pick the quantity to split the change into volume, mix and price.</p>
        <select className="insp-select" aria-label="Volume measure" value="" onChange={(e) => setVolume(e.target.value)}>
          <option value="" disabled>Choose a quantity…</option>
          {volumeChoices.map((m) => <option key={m.name} value={m.name}>{humanLabel(m.name)}</option>)}
        </select>
      </section>
    );
  }
  if (!data) {
    return error ? <section className="insp-block"><h3>Price, volume &amp; mix</h3><p className="insp-caption">{error}</p></section>
      : <div className="skeleton skeleton--list" aria-busy="true" aria-label="Loading price, volume and mix" />;
  }
  const e = data.effects;
  const steps = [
    { label: "Volume", delta: e.volume },
    ...(data.dimension ? [{ label: "Mix", delta: e.mix }] : []),
    { label: "Price", delta: e.price },
    ...(e.unexplained ? [{ label: "Unexplained", delta: e.unexplained }] : []),
  ];
  const vs = data.volume_subtype;
  return (
    <section className={`insp-block${loading ? " is-stale" : ""}`}>
      <div className="insp-block__head">
        <h3>Price, volume &amp; mix</h3>
        <div className="insp-inline">
          <select className="insp-select" aria-label="Volume measure" value={data.volume} onChange={(ev) => setVolume(ev.target.value)}>
            {data.volume_candidates.map((m) => <option key={m} value={m}>{humanLabel(m)}</option>)}
          </select>
          {data.dimension && (
            <select className="insp-select" aria-label="Mix across" value={data.dimension} onChange={(ev) => setDimension(ev.target.value)}>
              {data.candidates.map((d) => <option key={d} value={d}>across {humanLabel(d)}</option>)}
            </select>
          )}
        </div>
      </div>
      <p className="insp-explain">
        {humanLabel(data.volume)} went from {formatNumber(data.a.volume, vs)} to {formatNumber(data.b.volume, vs)} and the
        average price from {formatNumber(data.a.avg_price, data.subtype)} to {formatNumber(data.b.avg_price, data.subtype)}.
        Selling more or less moved {humanLabel(data.measure).toLowerCase()} by <b>{signed(e.volume, data.subtype)}</b>,
        {data.dimension && <> the shift between {humanLabel(data.dimension).toLowerCase()} values by <b>{signed(e.mix, data.subtype)}</b>,</>}
        {" "}and price changes by <b>{signed(e.price, data.subtype)}</b>.
      </p>
      <Waterfall height={200} subtype={data.subtype}
        start={{ label: data.a.label, value: data.a.value }} steps={steps}
        end={{ label: data.b.label, value: data.b.value }} />
      {e.unexplained !== 0 && (
        <p className="insp-caption">
          {signed(e.unexplained, data.subtype)} can't be explained as price × quantity — some rows carry
          {" "}{humanLabel(data.measure).toLowerCase()} without any {humanLabel(data.volume).toLowerCase()}.
        </p>
      )}
      {data.dimension && <div className="records__scroll pvm-table" tabIndex={0} role="region" aria-label="Price, volume and mix by segment">
        <table className="records__table">
          <thead>
            <tr>
              <th scope="col"><span className="th-pad">{humanLabel(data.dimension)}</span></th>
              <th scope="col" className="num"><span className="th-pad">{humanLabel(data.volume)}</span></th>
              <th scope="col" className="num"><span className="th-pad">Price</span></th>
              <th scope="col" className="num"><span className="th-pad">Mix</span></th>
              <th scope="col" className="num"><span className="th-pad">Price effect</span></th>
            </tr>
          </thead>
          <tbody>
            {data.segments.map((s) => (
              <tr key={String(s.name)}>
                <td>{s.name == null ? "(blank)" : String(s.name)}</td>
                <td className="num">{formatNumber(s.qa, vs)} → {formatNumber(s.qb, vs)}</td>
                <td className="num">{formatNumber(s.price_a, data.subtype)} → {formatNumber(s.price_b, data.subtype)}</td>
                <td className="num">{signed(s.mix, data.subtype)}</td>
                <td className="num">{signed(s.price, data.subtype)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>}
    </section>
  );
}

/** "Why it changed": A vs B, reconciled step by step. */
export default function ChangeAnalysis({ datasetId, ctx, go, measures }) {
  const compare = ctx.compare || "previous";
  const key = JSON.stringify([datasetId, ctx.measure, ctx.agg, ctx.filters, ctx.date_from, ctx.date_to, ctx.grain, compare, ctx.dimension]);
  const { data, error, loading } = useFetch(
    () => getVariance(datasetId, { ...ctx, compare }, { dimension: ctx.dimension || undefined }), key);

  const head = (
    <div className="insp-block__head">
      <h3>Compared with</h3>
      <div className="seg" role="group" aria-label="Compare with">
        {[["previous", `previous ${ctx.grain}`], ["year_ago", "a year ago"]].map(([k, label]) => (
          <button key={k} aria-pressed={compare === k} className={compare === k ? "is-on" : ""}
            onClick={() => go({ ...ctx, compare: k }, true)}>{label}</button>
        ))}
      </div>
    </div>
  );

  if (error) return <section className="insp-block">{head}<div className="empty-panel">{error}</div></section>;
  if (!data) return <section className="insp-block">{head}<div className="skeleton skeleton--list" aria-busy="true" aria-label="Loading the change" /></section>;

  const sub = data.subtype;
  const dim = data.dimension;
  const steps = data.steps.map((s) => ({ label: memberLabel(s), delta: s.delta, clickable: !s.blank, name: s.name }));
  if (data.other) steps.push({ label: `Other (${data.other.count})`, delta: data.other.delta });
  const drill = (name) => go({ ...drillInto(ctx, dim, String(name)), tab: "change" });

  return (
    <>
      <section className={`insp-block${loading ? " is-stale" : ""}`}>
        {head}
        <p className="change-headline">
          <span className={`cmp-chip__value change-pct change-pct--${data.delta > 0 ? "up" : data.delta < 0 ? "down" : "flat"}`}>
            {pctText(data.pct) || signed(data.delta, sub)}
          </span>
          {data.summary}
        </p>
        {data.significance && <Significance sig={data.significance} grain={data.grain} subtype={sub} />}
        {data.note && <p className="insp-caption">{data.note}</p>}
      </section>

      {dim && (
        <section className="insp-block">
          <div className="insp-block__head">
            <h3>Where the change came from</h3>
            <select className="insp-select" aria-label="Split the change by" value={ctx.dimension || ""}
              onChange={(e) => go({ ...ctx, dimension: e.target.value || null }, true)}>
              <option value="">Auto — {humanLabel(data.auto_dimension || "")}</option>
              {data.ranking.map((r) => <option key={r.dimension} value={r.dimension}>{humanLabel(r.dimension)}</option>)}
            </select>
          </div>
          {data.ranking.length > 1 && (
            <p className="insp-caption">
              Best explained by{" "}
              {data.ranking.slice(0, 3).map((r, i) => (
                <span key={r.dimension}>
                  {i > 0 && " · "}
                  <button className="link-btn link-btn--inline" onClick={() => go({ ...ctx, dimension: r.dimension }, true)}>
                    {humanLabel(r.dimension)}
                  </button>{" "}({Math.round(r.score * 100)}% in one value)
                </span>
              ))}
            </p>
          )}
          <Waterfall subtype={sub} start={{ label: data.a.label, value: data.a.value }}
            steps={steps} end={{ label: data.b.label, value: data.b.value }}
            onStep={(s) => drill(s.name)} />
          <ul className="drill-list">
            {data.steps.map((s) => (
              <li key={memberLabel(s)}>
                <button className="drill-row drill-row--change" disabled={s.blank} onClick={() => drill(s.name)}>
                  <span className="drill-row__name">{memberLabel(s)}</span>
                  <span className="drill-row__ab">{formatNumber(s.a, sub)} → {formatNumber(s.b, sub)}</span>
                  <span className={`drill-row__value delta--${s.delta >= 0 ? "up" : "down"}`}>{signed(s.delta, sub)}</span>
                  <span className="drill-row__share">
                    {s.share_of_change != null ? `${Math.round(s.share_of_change * 100)}%` : ""}
                  </span>
                </button>
              </li>
            ))}
            {data.other && (
              <li className="drill-row drill-row--static">
                <span className="drill-row__name">Other ({data.other.count} more)</span>
                <span className="drill-row__ab">{formatNumber(data.other.a, sub)} → {formatNumber(data.other.b, sub)}</span>
                <span className={`drill-row__value delta--${data.other.delta >= 0 ? "up" : "down"}`}>{signed(data.other.delta, sub)}</span>
                <span className="drill-row__share">
                  {data.other.share_of_change != null ? `${Math.round(data.other.share_of_change * 100)}%` : ""}
                </span>
              </li>
            )}
          </ul>
          <p className="insp-caption">The steps add up exactly to the change. Click one to see why it moved.</p>
        </section>
      )}

      {ctx.agg === "sum" && measures.length > 1 && <PriceVolumeMix datasetId={datasetId} ctx={ctx} measures={measures} />}
    </>
  );
}
