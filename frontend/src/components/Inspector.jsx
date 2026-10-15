import { useEffect, useRef, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { errorText, getBreakdown, getInspect } from "../api";
import { formatNumber, humanLabel } from "../format";
import {
  AGG_LABELS, GRAINS, crumbs, drillInto, drillPeriod, pctText, truncateCtx,
} from "../drill";
import RecordsTable from "./RecordsTable";

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "breakdown", label: "Breakdown" },
  { key: "records", label: "Records" },
  { key: "proof", label: "How it's calculated" },
];

function ShareBar({ pct }) {
  if (pct == null) return null;
  return (
    <span className="share-bar" aria-hidden>
      <span className="share-bar__fill" style={{ width: `${Math.max(1.5, Math.min(100, pct))}%` }} />
    </span>
  );
}

function CompareChip({ label, cmp, subtype }) {
  if (!cmp) return null;
  const dir = cmp.delta > 0 ? "up" : cmp.delta < 0 ? "down" : "flat";
  return (
    <div className={`cmp-chip cmp-chip--${dir}`}>
      <span className="cmp-chip__label">{label} {cmp.period}</span>
      <span className="cmp-chip__value">
        {pctText(cmp.pct) || "—"}{" "}
        <span className="cmp-chip__abs">({cmp.delta >= 0 ? "+" : "−"}{formatNumber(Math.abs(cmp.delta), subtype)})</span>
      </span>
    </div>
  );
}

function TrendTip({ active, payload, subtype }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip__label">{p.period}</div>
      <div className="chart-tooltip__value">{formatNumber(p.value, subtype)} · {p.rows.toLocaleString("en-IN")} rows</div>
      <div className="chart-tooltip__hint">click to drill into this period</div>
    </div>
  );
}

function ItemRow({ item, subtype, onClick }) {
  return (
    <li>
      <button className="drill-row" onClick={onClick}>
        <span className="drill-row__name">{String(item.name)}</span>
        <ShareBar pct={item.share_pct} />
        <span className="drill-row__value">{formatNumber(item.value, subtype)}</span>
        <span className="drill-row__share">{item.share_pct != null ? `${item.share_pct}%` : `${item.rows.toLocaleString("en-IN")} rows`}</span>
      </button>
    </li>
  );
}

function Overview({ data, ctx, go }) {
  const sub = data.subtype;
  const trend = data.trend;
  const lastPeriod = trend?.points?.at(-1)?.period;
  return (
    <>
      {trend && (
        <section className="insp-block">
          <div className="insp-block__head">
            <h3>Trend</h3>
            <div className="seg" role="group" aria-label="Time grain">
              {GRAINS.map((g) => (
                <button key={g} aria-pressed={ctx.grain === g} className={ctx.grain === g ? "is-on" : ""}
                  onClick={() => go({ ...ctx, grain: g }, true)}>{g[0].toUpperCase() + g.slice(1)}</button>
              ))}
            </div>
          </div>
          {trend.points.length === 0 ? (
            <div className="empty-panel">No dated rows in this slice.</div>
          ) : (
            <ResponsiveContainer width="100%" height={170}>
              <BarChart data={trend.points} margin={{ top: 6, right: 4, left: 0, bottom: 0 }}
                onClick={(s) => {
                  const p = trend.points[Number(s?.activeIndex ?? s?.activeTooltipIndex)];
                  if (p) go(drillPeriod(ctx, p.from, p.to));
                }}>
                <CartesianGrid stroke="var(--gridline)" vertical={false} />
                <XAxis dataKey="period" stroke="var(--baseline)" tick={{ fill: "var(--text-muted)", fontSize: 10 }}
                  tickLine={false} minTickGap={16} />
                <YAxis stroke="var(--baseline)" tick={{ fill: "var(--text-muted)", fontSize: 10 }} tickLine={false}
                  axisLine={false} width={56} tickFormatter={(v) => formatNumber(v, sub)} />
                <Tooltip content={<TrendTip subtype={sub} />} cursor={{ fill: "var(--gridline)" }} />
                <Bar dataKey="value" radius={[3, 3, 0, 0]} cursor="pointer" maxBarSize={28}>
                  {trend.points.map((p) => (
                    <Cell key={p.period}
                      fill={p.period === lastPeriod && trend.latest_period_partial ? "var(--baseline)" : "var(--series-1)"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
          {trend.comparison && (
            <p className="insp-caption">
              Latest {ctx.grain}: <b>{trend.comparison.period}</b> — {formatNumber(trend.comparison.value, sub)}
              {trend.latest_period_partial && " (incomplete — data ends " + trend.data_through + ")"}
            </p>
          )}
        </section>
      )}

      {data.stats && (
        <section className="insp-block">
          <h3>Spread of {humanLabel(data.measure)}</h3>
          <dl className="stat-grid">
            <div><dt>Rows</dt><dd>{data.row_count.toLocaleString("en-IN")}</dd></div>
            <div><dt>Minimum</dt><dd>{formatNumber(data.stats.min, sub)}</dd></div>
            <div><dt>Median</dt><dd>{formatNumber(data.stats.median, sub)}</dd></div>
            <div><dt>Average</dt><dd>{formatNumber(data.stats.avg, sub)}</dd></div>
            <div><dt>Maximum</dt><dd>{formatNumber(data.stats.max, sub)}</dd></div>
            <div><dt>Std. deviation</dt><dd>{formatNumber(data.stats.std, sub)}</dd></div>
          </dl>
        </section>
      )}

      {data.contributors.length > 0 && (
        <section className="insp-block">
          <h3>What makes up this number</h3>
          <div className="contrib-grid">
            {data.contributors.map((c) => (
              <div key={c.dimension} className="contrib">
                <div className="contrib__head">
                  <span>By {humanLabel(c.dimension)}</span>
                  <button className="link-btn"
                    onClick={() => go({ ...ctx, tab: "breakdown", dimension: c.dimension })}>
                    All {c.distinct} ›
                  </button>
                </div>
                <ul className="drill-list">
                  {c.items.map((it) => (
                    <ItemRow key={String(it.name)} item={it} subtype={sub}
                      onClick={() => go(drillInto(ctx, c.dimension, String(it.name)))} />
                  ))}
                  {c.others && (
                    <li>
                      <button className="drill-row drill-row--others"
                        onClick={() => go({ ...ctx, tab: "breakdown", dimension: c.dimension })}>
                        <span className="drill-row__name">Other ({c.others.count} more)</span>
                        <ShareBar pct={c.others.share_pct} />
                        <span className="drill-row__value">{formatNumber(c.others.value, sub)}</span>
                        <span className="drill-row__share">{c.others.share_pct != null ? `${c.others.share_pct}%` : ""}</span>
                      </button>
                    </li>
                  )}
                </ul>
              </div>
            ))}
          </div>
        </section>
      )}
    </>
  );
}

function BreakdownTab({ datasetId, data, ctx, go }) {
  const dims = data.dimensions.filter((d) => !d.pinned);
  const dim = dims.some((d) => d.name === ctx.dimension) ? ctx.dimension : dims[0]?.name;
  const [limit, setLimit] = useState(50);
  const [bd, setBd] = useState(null);
  const [error, setError] = useState(null);
  const key = JSON.stringify([ctx.measure, ctx.agg, ctx.filters, ctx.date_from, ctx.date_to, dim, limit]);

  useEffect(() => { setLimit(50); }, [dim]);
  useEffect(() => {
    if (!dim) return;
    let live = true;
    setError(null);
    getBreakdown(datasetId, ctx, dim, limit)
      .then((d) => { if (live) setBd(d); })
      .catch((e) => { if (live) setError(errorText(e, "Could not load the breakdown.")); });
    return () => { live = false; };
    // ctx is captured through key
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetId, key]);

  if (!dim) {
    return <div className="empty-panel">Every category is already pinned — see the records for the detail.</div>;
  }
  return (
    <section className="insp-block">
      <div className="insp-block__head">
        <h3>Split by</h3>
        <select className="insp-select" value={dim} aria-label="Dimension to split by"
          onChange={(e) => go({ ...ctx, dimension: e.target.value }, true)}>
          {dims.map((d) => <option key={d.name} value={d.name}>{humanLabel(d.name)}</option>)}
        </select>
      </div>
      {error && <div className="empty-panel">{error}</div>}
      {!bd && !error && <div className="skeleton skeleton--list" aria-busy="true" aria-label="Loading breakdown" />}
      {bd && !error && (
        <>
          <p className="insp-caption">
            {bd.distinct.toLocaleString("en-IN")} {humanLabel(bd.dimension).toLowerCase()} values · click one to drill deeper
          </p>
          <ul className="drill-list drill-list--full">
            {bd.items.map((it) => (
              <ItemRow key={String(it.name)} item={it} subtype={bd.subtype}
                onClick={() => go(drillInto(ctx, bd.dimension, String(it.name)))} />
            ))}
          </ul>
          {bd.others && (
            <div className="drill-more">
              <span>{bd.others.count.toLocaleString("en-IN")} more · {formatNumber(bd.others.value, bd.subtype)}
                {bd.others.share_pct != null && ` (${bd.others.share_pct}%)`}</span>
              {limit < 500 && <button className="views-btn" onClick={() => setLimit((l) => Math.min(500, l + 100))}>Show more</button>}
            </div>
          )}
        </>
      )}
    </section>
  );
}

function Proof({ data }) {
  const [copied, setCopied] = useState(false);
  const f = Object.entries(data.context.filters || {});
  const copy = async () => {
    try { await navigator.clipboard.writeText(data.sql); setCopied(true); setTimeout(() => setCopied(false), 1500); }
    catch { /* clipboard blocked — the SQL is still selectable */ }
  };
  return (
    <>
      <section className="insp-block">
        <h3>In plain words</h3>
        <p className="insp-explain">{data.explanation}</p>
      </section>
      <section className="insp-block">
        <h3>Conditions applied</h3>
        {f.length === 0 && !data.context.date_from && !data.context.date_to ? (
          <p className="insp-caption">None — every row you can access is included.</p>
        ) : (
          <dl className="cond-list">
            {f.map(([k, v]) => <div key={k}><dt>{humanLabel(k)}</dt><dd>= {v}</dd></div>)}
            {(data.context.date_from || data.context.date_to) && (
              <div><dt>{humanLabel(data.context.date_column || "date")}</dt>
                <dd>{data.context.date_from || "…"} → {data.context.date_to || "…"} (inclusive)</dd></div>
            )}
          </dl>
        )}
      </section>
      <section className="insp-block">
        <div className="insp-block__head">
          <h3>The exact query</h3>
          <button className="views-btn" onClick={copy}>{copied ? "Copied" : "Copy SQL"}</button>
        </div>
        <pre className="sql-block"><code>{data.sql}</code></pre>
        <p className="insp-caption">
          Computed directly from your data by this query — no AI is involved in producing the number.
        </p>
      </section>
    </>
  );
}

/**
 * The drill-down drawer. Non-modal: the dashboard stays live behind it, so
 * clicking another chart simply re-targets the drawer.
 */
export default function Inspector({ datasetId, ctx, onNavigate, onClose, onApply }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const closeRef = useRef(null);
  const key = JSON.stringify([ctx.measure, ctx.agg, ctx.filters, ctx.date_from, ctx.date_to, ctx.grain]);

  useEffect(() => {
    let live = true;
    setError(null);
    setLoading(true);
    getInspect(datasetId, ctx)
      .then((d) => { if (live) setData(d); })
      .catch((e) => { if (live) setError(errorText(e, "Could not open this number.")); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
    // ctx is captured through key
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetId, key]);

  useEffect(() => { closeRef.current?.focus(); }, []);
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const go = (next, replace = false) => onNavigate(next, { replace });
  const trail = crumbs(ctx);
  const sub = data?.subtype;
  const cmp = data?.trend?.comparison;
  const tab = TABS.some((t) => t.key === ctx.tab) ? ctx.tab : "overview";

  return (
    <aside className="inspector no-export" role="dialog" aria-modal="false" aria-labelledby="inspector-value">
      <div className="inspector__head">
        <nav className="crumbs" aria-label="Drill path">
          <ol>
            {trail.map((c, i) => (
              <li key={i}>
                {i < trail.length - 1 ? (
                  <button className="crumbs__btn" onClick={() => go(truncateCtx(ctx, i))}>{c.label}</button>
                ) : (
                  <span className="crumbs__current" aria-current="page">{c.label}</span>
                )}
              </li>
            ))}
          </ol>
        </nav>
        <button ref={closeRef} className="icon-btn" aria-label="Close details" onClick={onClose}>✕</button>
      </div>

      {error && <div className="empty-panel">{error}</div>}
      {!error && !data && <div className="skeleton skeleton--hero" aria-busy="true" aria-label="Loading" />}

      {!error && data && (
        <>
          <div className={`inspector__hero${loading ? " is-stale" : ""}`} aria-busy={loading}>
            <div className="inspector__pickers">
              <select className="insp-select" aria-label="Calculation" value={ctx.agg}
                onChange={(e) => go({ ...ctx, agg: e.target.value }, true)}>
                {Object.entries(AGG_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
              {ctx.agg !== "count" && data.measures.length > 0 && (
                <>
                  <span className="inspector__of">of</span>
                  <select className="insp-select" aria-label="Measure" value={data.measure || ""}
                    onChange={(e) => go({ ...ctx, measure: e.target.value }, true)}>
                    {data.measures.map((m) => <option key={m.name} value={m.name}>{humanLabel(m.name)}</option>)}
                  </select>
                </>
              )}
            </div>
            <div id="inspector-value" className="inspector__value">{formatNumber(data.value, sub)}</div>
            <div className="inspector__sub">
              across {data.row_count.toLocaleString("en-IN")} {data.row_count === 1 ? "row" : "rows"} of {data.dataset.name}
            </div>
            {cmp && (cmp.previous || cmp.year_ago) && (
              <div className="inspector__compare">
                <span className="insp-caption">Latest {ctx.grain} ({cmp.period}) vs</span>
                <CompareChip label="previous" cmp={cmp.previous} subtype={sub} />
                <CompareChip label="year ago" cmp={cmp.year_ago} subtype={sub} />
              </div>
            )}
            {data.notes.length > 0 && (
              <ul className="insp-notes">{data.notes.map((n) => <li key={n}>{n}</li>)}</ul>
            )}
          </div>

          <div className="insp-tabs" role="tablist" aria-label="Detail views">
            {TABS.map((t) => (
              <button key={t.key} role="tab" id={`insp-tab-${t.key}`} aria-selected={tab === t.key}
                aria-controls="insp-panel" className={tab === t.key ? "is-on" : ""}
                onClick={() => go({ ...ctx, tab: t.key }, true)}>{t.label}</button>
            ))}
          </div>

          <div className="inspector__body" role="tabpanel" id="insp-panel" aria-labelledby={`insp-tab-${tab}`}>
            {tab === "overview" && <Overview data={data} ctx={ctx} go={go} />}
            {tab === "breakdown" && <BreakdownTab datasetId={datasetId} data={data} ctx={ctx} go={go} />}
            {tab === "records" && <RecordsTable datasetId={datasetId} slice={ctx} name={data.dataset.name} />}
            {tab === "proof" && <Proof data={data} />}
          </div>

          <div className="inspector__foot">
            <button className="views-btn views-btn--accent" onClick={() => onApply(ctx)}>Show this on the dashboard</button>
            {tab !== "records" && <button className="views-btn" onClick={() => go({ ...ctx, tab: "records" }, true)}>See the rows</button>}
          </div>
        </>
      )}
    </aside>
  );
}
