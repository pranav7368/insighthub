import { useCallback, useEffect, useRef, useState } from "react";
import { createView, deleteView, exportDatasetCsv, getDashboard, getExplain, getScatter, listMetrics, listViews, updateView } from "../api";
import { exportPdf, exportPng } from "../export";
import KpiCard from "./KpiCard";
import CorrelationHeatmap from "./CorrelationHeatmap";
import ScatterPlot from "./ScatterChart";
import TreemapChart from "./TreemapChart";
import GrowthStrip from "./GrowthStrip";
import ParetoChart from "./ParetoChart";
import AiNarrative from "./AiNarrative";
import InsightsPanel from "./InsightsPanel";
import ForecastChart from "./ForecastChart";
import BreakdownChart from "./BreakdownChart";
import ContributionDonut from "./ContributionDonut";
import DistributionCard from "./DistributionCard";
import FilterBar from "./FilterBar";
import FilterChips from "./FilterChips";
import DateRangePresets from "./DateRangePresets";
import DataProfile from "./DataProfile";
import MapChart from "./MapChart";
import CertifiedMetrics from "./CertifiedMetrics";
import DriverAnalysis from "./DriverAnalysis";
import ViewsBar from "./ViewsBar";
import { humanLabel } from "../format";
import { mappableFraction } from "../geo";

// stable JSON for comparing a live config against a saved one (dirty check)
const canonConfig = (c) =>
  JSON.stringify({
    filters: Object.fromEntries(Object.entries(c.filters || {}).sort()),
    date_from: c.date_from || null,
    date_to: c.date_to || null,
    measure: c.measure || null,
    hidden_sections: [...(c.hidden_sections || [])].sort(),
  });

export default function DashboardView({ datasetId }) {
  const [dashboard, setDashboard] = useState(null);
  const [activeMeasure, setActiveMeasure] = useState(null);
  const [filters, setFilters] = useState({});
  const [dateFrom, setDateFrom] = useState();
  const [dateTo, setDateTo] = useState();
  const [error, setError] = useState(null);
  const [pair, setPair] = useState(null);            // user-chosen scatter pair
  const [customScatter, setCustomScatter] = useState(null);
  const [exporting, setExporting] = useState(null);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [hiddenSections, setHiddenSections] = useState([]);
  const [views, setViews] = useState([]);
  const [activeViewId, setActiveViewId] = useState(null);
  const [metrics, setMetrics] = useState([]);
  const [explainData, setExplainData] = useState(null);
  const contentRef = useRef(null);

  const currentConfig = () => ({
    filters,
    date_from: dateFrom || null,
    date_to: dateTo || null,
    measure: activeMeasure || null,
    hidden_sections: hiddenSections,
  });

  const applyView = (view) => {
    const c = view.config || {};
    setFilters(c.filters || {});
    setDateFrom(c.date_from || undefined);
    setDateTo(c.date_to || undefined);
    setActiveMeasure(c.measure || null);
    setHiddenSections(Array.isArray(c.hidden_sections) ? c.hidden_sections : []);
    setActiveViewId(view.view_id);
  };

  const reloadViews = () => listViews(datasetId).then(setViews).catch(() => setViews([]));

  const saveView = async (name) => {
    try {
      const v = await createView(datasetId, name, currentConfig(), views.length === 0);
      await reloadViews();
      setActiveViewId(v.view_id);
    } catch (e) { setError(e?.response?.data?.detail || "Could not save the view."); }
  };
  const updateActiveView = async () => {
    if (!activeViewId) return;
    try { await updateView(activeViewId, { config: currentConfig() }); await reloadViews(); }
    catch (e) { setError(e?.response?.data?.detail || "Could not update the view."); }
  };
  const setDefaultActiveView = async () => {
    if (!activeViewId) return;
    try { await updateView(activeViewId, { is_default: true }); await reloadViews(); }
    catch (e) { setError(e?.response?.data?.detail || "Could not set the default."); }
  };
  const deleteActiveView = async () => {
    if (!activeViewId) return;
    try { await deleteView(activeViewId); setActiveViewId(null); await reloadViews(); }
    catch (e) { setError(e?.response?.data?.detail || "Could not delete the view."); }
  };
  const toggleSection = (key) =>
    setHiddenSections((h) => (h.includes(key) ? h.filter((x) => x !== key) : [...h, key]));

  const show = (key) => !hiddenSections.includes(key);
  const activeView = views.find((v) => v.view_id === activeViewId) || null;
  const viewDirty = activeView ? canonConfig(activeView.config) !== canonConfig(currentConfig()) : false;

  const runExport = async (kind) => {
    if (!contentRef.current) return;
    setExporting(kind);
    try {
      const name = dashboard?.dataset?.name || "dashboard";
      if (kind === "png") await exportPng(contentRef.current, name);
      else await exportPdf(contentRef.current, name);
    } catch (e) {
      setError("Export failed. Try again.");
    } finally {
      setExporting(null);
    }
  };

  useEffect(() => {
    setActiveMeasure(null); setFilters({}); setDateFrom(undefined); setDateTo(undefined); setPair(null);
    setHiddenSections([]); setActiveViewId(null);
    listViews(datasetId)
      .then((vs) => {
        setViews(vs);
        const def = vs.find((v) => v.is_default);
        if (def) applyView(def);   // auto-apply the saved default view
      })
      .catch(() => setViews([]));
    listMetrics(datasetId).then(setMetrics).catch(() => setMetrics([]));
  }, [datasetId]);

  // when the user clicks a heatmap cell, fetch that pair (respecting filters)
  useEffect(() => {
    if (!pair) { setCustomScatter(null); return; }
    const params = { ...filters, x: pair.x, y: pair.y };
    if (dateFrom) params.date_from = dateFrom;
    if (dateTo) params.date_to = dateTo;
    getScatter(datasetId, params).then(setCustomScatter).catch(() => setCustomScatter(null));
  }, [pair, datasetId, filters, dateFrom, dateTo]);

  const load = useCallback(async () => {
    setError(null);
    try {
      const params = { ...filters };
      if (dateFrom) params.date_from = dateFrom;
      if (dateTo) params.date_to = dateTo;
      if (activeMeasure) params.measure = activeMeasure;
      const data = await getDashboard(datasetId, params);
      setDashboard(data);
      if (!activeMeasure && data.chosen_measure) setActiveMeasure(data.chosen_measure);
    } catch (err) {
      setError(err?.response?.data?.detail || "Could not load the dashboard.");
    }
  }, [datasetId, filters, dateFrom, dateTo, activeMeasure]);

  useEffect(() => { load(); }, [load]);

  // driver / root-cause analysis, following the active measure
  useEffect(() => {
    getExplain(datasetId, activeMeasure || undefined)
      .then(setExplainData)
      .catch(() => setExplainData(null));
  }, [datasetId, activeMeasure]);

  // click a bar/slice -> toggle that dimension=value filter -> whole dashboard recomputes
  const toggleFilter = (dim, value) => {
    if (value == null) return;
    setFilters((prev) => {
      const next = { ...prev };
      if (next[dim] === value) delete next[dim];
      else next[dim] = value;
      return next;
    });
  };
  const removeFilter = (dim) =>
    setFilters((prev) => {
      const next = { ...prev };
      delete next[dim];
      return next;
    });

  if (error) return <div className="empty-panel">{error}</div>;
  if (!dashboard) return <div className="empty-panel">Loading…</div>;

  const subtypeOf = (m) => dashboard.kpis.find((k) => k.column === m)?.subtype;
  const measure = activeMeasure || dashboard.chosen_measure;
  const distNames = Object.keys(dashboard.distributions || {});

  // pick a geographic breakdown dimension (>=60% of its values are placeable)
  const geoEntry = Object.entries(dashboard.breakdowns || {}).find(
    ([, bd]) => (bd.data?.length || 0) >= 2 && mappableFraction((bd.data || []).map((d) => d.name)) >= 0.6
  );

  const activeFilterCount = Object.keys(filters).length + (dateFrom ? 1 : 0);

  return (
    <div className="dash-layout">
      <div className={`filter-panel${filtersOpen ? " filter-panel--open" : ""}`}>
        <FilterBar
          filterOptions={dashboard.filter_options}
          activeFilters={filters}
          onFilterChange={(name, value) =>
            setFilters((prev) => {
              const next = { ...prev };
              if (value) next[name] = value; else delete next[name];
              return next;
            })
          }
          dateFrom={dateFrom} dateTo={dateTo}
          onDateFromChange={setDateFrom} onDateToChange={setDateTo}
          onReset={() => { setFilters({}); setDateFrom(undefined); setDateTo(undefined); }}
        />
      </div>

      <div className="dash-content" ref={contentRef}>
        <div className="dash-topline">
          <div className="dash-topline__title">
            {dashboard.dataset?.name}
            <span className="dash-topline__rows">{dashboard.row_count_filtered?.toLocaleString("en-IN")} rows</span>
          </div>
          <div className="dash-topline__actions">
            <ViewsBar
              views={views} activeViewId={activeViewId} dirty={viewDirty}
              hiddenSections={hiddenSections}
              onApply={applyView} onToggleSection={toggleSection}
              onSave={saveView} onUpdate={updateActiveView}
              onDelete={deleteActiveView} onSetDefault={setDefaultActiveView}
            />
            <button className="filters-toggle no-export" onClick={() => setFiltersOpen((o) => !o)}>
              Filters{activeFilterCount > 0 ? ` (${activeFilterCount})` : ""}
            </button>
            <DateRangePresets
              dateSpan={dashboard.data_profile?.date_span}
              activeFrom={dateFrom}
              onApply={(from, to) => { setDateFrom(from); setDateTo(to); }}
              onClear={() => { setDateFrom(undefined); setDateTo(undefined); }}
            />
            <div className="export-btns no-export">
              <button onClick={() => runExport("pdf")} disabled={exporting}>
                {exporting === "pdf" ? "…" : "Export PDF"}
              </button>
              <button onClick={() => runExport("png")} disabled={exporting}>
                {exporting === "png" ? "…" : "PNG"}
              </button>
              <button onClick={() => exportDatasetCsv(datasetId, dashboard.dataset?.name)}>CSV</button>
            </div>
          </div>
        </div>

        <FilterChips filters={filters} onRemove={removeFilter} onClearAll={() => setFilters({})} />

        {show("kpis") && dashboard.kpis.length === 0 && (
          <div className="empty-panel">
            No numeric measures detected in this dataset. Use “Review columns” to fix the roles.
          </div>
        )}

        {show("kpis") && (
          <div className="kpi-row">
            {dashboard.kpis.map((kpi) => (
              <KpiCard key={kpi.column} kpi={kpi} active={kpi.column === measure}
                onSelect={() => setActiveMeasure(kpi.column)} />
            ))}
          </div>
        )}

        {show("metrics") && metrics.length > 0 && <CertifiedMetrics metrics={metrics} />}

        {show("growth") && <GrowthStrip growth={dashboard.growth} measure={measure} />}

        {show("insights") && <InsightsPanel insights={dashboard.insights} />}

        {show("drivers") && <DriverAnalysis explain={explainData} />}

        {show("narrative") && <AiNarrative datasetId={datasetId} />}

        {show("forecast") && measure && (
          <ForecastChart
            measure={measure} subtype={subtypeOf(measure)}
            forecast={dashboard.forecasts?.[measure]}
            anomalies={dashboard.anomalies?.[measure]}
          />
        )}

        {show("breakdowns") && (
          <div className="chart-grid">
            {Object.entries(dashboard.breakdowns).map(([dim, bd]) => (
              <BreakdownChart key={dim} dimensionName={dim} breakdown={bd}
                measure={measure} subtype={subtypeOf(measure)}
                onSelect={toggleFilter} activeValue={filters[dim]} />
            ))}
            {Object.entries(dashboard.breakdowns).slice(0, 1).map(([dim, bd]) => (
              <ContributionDonut key={`donut-${dim}`} dimensionName={dim} breakdown={bd}
                subtype={subtypeOf(measure)} onSelect={toggleFilter} activeValue={filters[dim]} />
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

        {show("correlations") && dashboard.correlations && (() => {
          const scatterToShow = customScatter || dashboard.scatter;
          const activePair = scatterToShow ? { x: scatterToShow.x, y: scatterToShow.y } : null;
          return (
            <div className="chart-grid">
              <CorrelationHeatmap correlations={dashboard.correlations} activePair={activePair}
                onSelect={(x, y) => setPair({ x, y })} />
              <ScatterPlot scatter={scatterToShow} />
            </div>
          );
        })()}

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
    </div>
  );
}
