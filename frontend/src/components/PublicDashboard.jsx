import { useEffect, useRef, useState } from "react";
import { getPublicDashboard } from "../api";
import { exportPdf, exportPng } from "../export";
import { mappableFraction } from "../geo";
import KpiCard from "./KpiCard";
import GrowthStrip from "./GrowthStrip";
import InsightsPanel from "./InsightsPanel";
import ForecastChart from "./ForecastChart";
import BreakdownChart from "./BreakdownChart";
import ContributionDonut from "./ContributionDonut";
import MapChart from "./MapChart";
import ParetoChart from "./ParetoChart";
import TreemapChart from "./TreemapChart";
import CorrelationHeatmap from "./CorrelationHeatmap";
import ScatterPlot from "./ScatterChart";
import DistributionCard from "./DistributionCard";
import DataProfile from "./DataProfile";

const noop = () => {};

export default function PublicDashboard({ token }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [exporting, setExporting] = useState(null);
  const contentRef = useRef(null);

  useEffect(() => {
    getPublicDashboard(token)
      .then(setData)
      .catch((err) =>
        setError(err?.response?.status === 404
          ? "This link is invalid or has expired."
          : "This dashboard could not be loaded."));
  }, [token]);

  const runExport = async (kind) => {
    if (!contentRef.current) return;
    setExporting(kind);
    try {
      const name = data?.dashboard?.dataset?.name || "dashboard";
      if (kind === "png") await exportPng(contentRef.current, name);
      else await exportPdf(contentRef.current, name);
    } catch { /* ignore */ } finally { setExporting(null); }
  };

  if (error) {
    return (
      <div className="public-shell">
        <div className="empty-state"><h2>Link unavailable</h2><p>{error}</p></div>
      </div>
    );
  }
  if (!data) return <div className="public-shell"><div className="empty-panel">Loading…</div></div>;

  const dashboard = data.dashboard;
  const hidden = data.meta?.hidden_sections || [];
  const show = (k) => !hidden.includes(k);
  const measure = dashboard.chosen_measure;
  const subtypeOf = (m) => dashboard.kpis.find((k) => k.column === m)?.subtype;
  const distNames = Object.keys(dashboard.distributions || {});
  const geoEntry = Object.entries(dashboard.breakdowns || {}).find(
    ([, bd]) => (bd.data?.length || 0) >= 2 && mappableFraction((bd.data || []).map((d) => d.name)) >= 0.6
  );

  return (
    <div className="public-shell">
      <header className="public-header">
        <div className="brand"><span className="brand__logo">◧</span> InsightHub</div>
        <span className="public-badge">Read-only shared view</span>
        <div className="export-btns no-export" style={{ marginLeft: "auto" }}>
          <button onClick={() => runExport("pdf")} disabled={exporting}>
            {exporting === "pdf" ? "…" : "Export PDF"}
          </button>
          <button onClick={() => runExport("png")} disabled={exporting}>
            {exporting === "png" ? "…" : "PNG"}
          </button>
        </div>
      </header>

      <div className="dash-content public-content" ref={contentRef}>
        <div className="dash-topline">
          <div className="dash-topline__title">
            {dashboard.dataset?.name}
            <span className="dash-topline__rows">
              {dashboard.row_count_filtered?.toLocaleString("en-IN")} rows
            </span>
          </div>
        </div>

        {show("kpis") && (
          <div className="kpi-row">
            {dashboard.kpis.map((kpi) => (
              <KpiCard key={kpi.column} kpi={kpi} active={kpi.column === measure} onSelect={noop} />
            ))}
          </div>
        )}

        {show("growth") && <GrowthStrip growth={dashboard.growth} measure={measure} />}
        {show("insights") && <InsightsPanel insights={dashboard.insights} />}

        {show("forecast") && measure && (
          <ForecastChart measure={measure} subtype={subtypeOf(measure)}
            forecast={dashboard.forecasts?.[measure]} anomalies={dashboard.anomalies?.[measure]} />
        )}

        {show("breakdowns") && (
          <div className="chart-grid">
            {Object.entries(dashboard.breakdowns).map(([dim, bd]) => (
              <BreakdownChart key={dim} dimensionName={dim} breakdown={bd}
                measure={measure} subtype={subtypeOf(measure)} onSelect={noop} />
            ))}
            {Object.entries(dashboard.breakdowns).slice(0, 1).map(([dim, bd]) => (
              <ContributionDonut key={`donut-${dim}`} dimensionName={dim} breakdown={bd}
                subtype={subtypeOf(measure)} onSelect={noop} />
            ))}
          </div>
        )}

        {show("map") && geoEntry && (
          <MapChart dimensionName={geoEntry[0]} breakdown={geoEntry[1]}
            measure={measure} subtype={subtypeOf(measure)} />
        )}

        {show("pareto") && dashboard.pareto && dashboard.pareto.total_categories > 2 && (
          <ParetoChart pareto={dashboard.pareto} />
        )}

        {show("treemap") && dashboard.treemap && (
          <TreemapChart treemap={dashboard.treemap} subtype={subtypeOf(measure)} />
        )}

        {show("correlations") && dashboard.correlations && (
          <div className="chart-grid">
            <CorrelationHeatmap correlations={dashboard.correlations}
              activePair={dashboard.scatter ? { x: dashboard.scatter.x, y: dashboard.scatter.y } : null}
              onSelect={noop} />
            <ScatterPlot scatter={dashboard.scatter} />
          </div>
        )}

        {show("distributions") && distNames.length > 0 && (
          <div className="dist-section">
            <div className="section-title">Distribution of each measure</div>
            <div className="dist-grid">
              {distNames.map((name) => (
                <DistributionCard key={name} name={name} dist={dashboard.distributions[name]} />
              ))}
            </div>
          </div>
        )}

        {show("profile") && <DataProfile profile={dashboard.data_profile} />}
      </div>

      <footer className="public-footer">
        Built with <b>InsightHub</b> — every number computed from the data, never invented.
      </footer>
    </div>
  );
}
