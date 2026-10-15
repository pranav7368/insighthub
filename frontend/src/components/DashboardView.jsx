import { Suspense, lazy, useCallback, useEffect, useRef, useState } from "react";
import { createView, deleteView, errorText, exportDatasetCsv, getDashboard, getExplain, getScatter, getTargets, listMetrics, listViews, updateView } from "../api";
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
import DashSection from "./DashSection";
import DecompositionTree from "./DecompositionTree";
import ActionsPanel from "./ActionsPanel";
import Icon from "./Icon";
import Popover from "./Popover";
import DataMenu from "./DataMenu";
import { mappableFraction } from "../geo";
import { moveKey, moveKeyByStep, orderSections, resolveOrder } from "../sections";
import { buildUrlSearch, makeCtx, readUrlState, targetFor } from "../drill";
import { buildCommands } from "../palette";
import { formatDate, formatRange, humanLabel } from "../format";
import { SECTIONS } from "../sections";

// opened on demand, so their code is fetched on first use
const Inspector = lazy(() => import("./Inspector"));
const CommandPalette = lazy(() => import("./CommandPalette"));

const IS_MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || "");

// stable JSON for comparing a live config against a saved one (dirty check).
// hidden_sections is a set (sorted), section_order is a sequence (kept as-is).
const canonConfig = (c) =>
  JSON.stringify({
    filters: Object.fromEntries(Object.entries(c.filters || {}).sort()),
    date_from: c.date_from || null,
    date_to: c.date_to || null,
    measure: c.measure || null,
    hidden_sections: [...(c.hidden_sections || [])].sort(),
    section_order: [...(c.section_order || [])],
  });

// A URL that names this dataset owns the initial state (a shared or
// bookmarked drill); otherwise the saved default view does.
function initialFromUrl(datasetId) {
  const s = readUrlState(window.location.search);
  if (s.datasetId !== datasetId) return null;
  const owns = s.measure || s.inspect || s.dateFrom || s.dateTo || Object.keys(s.filters).length;
  return owns ? s : null;
}

export default function DashboardView({ datasetId, canEdit = false, onRequestAlert, manageActions = [], datasetMeta }) {
  const [fromUrl] = useState(() => initialFromUrl(datasetId));
  const [dashboard, setDashboard] = useState(null);
  const [activeMeasure, setActiveMeasure] = useState(fromUrl?.measure || null);
  const [filters, setFilters] = useState(fromUrl?.filters || {});
  const [dateFrom, setDateFrom] = useState(fromUrl?.dateFrom);
  const [dateTo, setDateTo] = useState(fromUrl?.dateTo);
  const [inspectCtx, setInspectCtx] = useState(fromUrl?.inspect || null);
  // how the next state change reaches the URL: "push" adds a history entry
  // (a drill step the back button can undo), "replace" edits in place, and
  // "skip" means the change came FROM the URL (back / forward)
  const navMode = useRef("replace");
  const [targets, setTargets] = useState([]);
  const [targetsVersion, setTargetsVersion] = useState(0);
  const returnFocus = useRef(null);
  const [menu, setMenu] = useState(null);                 // right-click menu on a data point
  const [paletteOpen, setPaletteOpen] = useState(false);  // Ctrl/⌘ K
  const closeMenu = useCallback(() => setMenu(null), []);
  const [error, setError] = useState(null);
  const [pair, setPair] = useState(null);            // user-chosen scatter pair
  const [customScatter, setCustomScatter] = useState(null);
  const [exporting, setExporting] = useState(null);
  const [nameRequest, setNameRequest] = useState(0);   // "Save as…" from the ⋯ menu
  const [hiddenSections, setHiddenSections] = useState([]);
  const [sectionOrder, setSectionOrder] = useState([]);
  const [arranging, setArranging] = useState(false);
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
    section_order: sectionOrder,
  });

  const applyView = (view) => {
    const c = view.config || {};
    setFilters(c.filters || {});
    setDateFrom(c.date_from || undefined);
    setDateTo(c.date_to || undefined);
    setActiveMeasure(c.measure || null);
    setHiddenSections(Array.isArray(c.hidden_sections) ? c.hidden_sections : []);
    setSectionOrder(Array.isArray(c.section_order) ? c.section_order : []);
    setActiveViewId(view.view_id);
  };

  const reloadViews = () => listViews(datasetId).then(setViews).catch(() => setViews([]));

  const saveView = async (name) => {
    try {
      const v = await createView(datasetId, name, currentConfig(), views.length === 0);
      await reloadViews();
      setActiveViewId(v.view_id);
    } catch (e) { setError(errorText(e, "Could not save the view.")); }
  };
  const updateActiveView = async () => {
    if (!activeViewId) return;
    try { await updateView(activeViewId, { config: currentConfig() }); await reloadViews(); }
    catch (e) { setError(errorText(e, "Could not update the view.")); }
  };
  const setDefaultActiveView = async () => {
    if (!activeViewId) return;
    try { await updateView(activeViewId, { is_default: true }); await reloadViews(); }
    catch (e) { setError(errorText(e, "Could not set the default.")); }
  };
  const deleteActiveView = async () => {
    if (!activeViewId) return;
    try { await deleteView(activeViewId); setActiveViewId(null); await reloadViews(); }
    catch (e) { setError(errorText(e, "Could not delete the view.")); }
  };
  const toggleSection = (key) =>
    setHiddenSections((h) => (h.includes(key) ? h.filter((x) => x !== key) : [...h, key]));

  // Dragging materializes the *full* key order (including hidden sections, so
  // they keep their place if they are shown again later).
  const reorderSection = (from, to) =>
    setSectionOrder((o) => moveKey(resolveOrder(o), from, to));
  const stepSection = (key, step, visibleKeys) =>
    setSectionOrder((o) => moveKeyByStep(resolveOrder(o), key, visibleKeys, step));
  const resetArrangement = () => { setSectionOrder([]); setHiddenSections([]); };

  const show = (key) => !hiddenSections.includes(key);
  const activeView = views.find((v) => v.view_id === activeViewId) || null;
  // A view that does not pin a measure follows whichever one the dashboard
  // picks, so that choice is not an unsaved change.
  const viewDirty = activeView
    ? canonConfig(activeView.config) !== canonConfig({
      ...currentConfig(), measure: activeView.config?.measure ? activeMeasure : null,
    })
    : false;

  const runExport = async (kind) => {
    if (!contentRef.current) return;
    setExporting(kind);
    try {
      const name = dashboard?.dataset?.name || "dashboard";
      if (kind === "png") await exportPng(contentRef.current, name);
      else await exportPdf(contentRef.current, name);
    } catch {
      // the underlying error is not actionable for the user
      setError("Export failed. Try again.");
    } finally {
      setExporting(null);
    }
  };

  // The component is keyed by dataset, so this runs once per dataset.
  useEffect(() => {
    listViews(datasetId)
      .then((vs) => {
        setViews(vs);
        const def = vs.find((v) => v.is_default);
        if (def && !fromUrl) applyView(def);   // auto-apply the saved default view
      })
      .catch(() => setViews([]));
    listMetrics(datasetId).then(setMetrics).catch(() => setMetrics([]));
  }, [datasetId]);   // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    getTargets(datasetId).then(setTargets).catch(() => setTargets([]));
  }, [datasetId, targetsVersion]);
  const targetsChanged = () => setTargetsVersion((v) => v + 1);

  // state -> URL
  useEffect(() => {
    const mode = navMode.current;
    navMode.current = "replace";
    if (mode === "skip") return;
    const search = buildUrlSearch({ datasetId, measure: activeMeasure, dateFrom, dateTo, filters, inspect: inspectCtx });
    if (search === window.location.search) return;
    const url = window.location.pathname + search + window.location.hash;
    if (mode === "push") window.history.pushState(null, "", url);
    else window.history.replaceState(null, "", url);
  }, [datasetId, activeMeasure, dateFrom, dateTo, filters, inspectCtx]);

  // URL -> state (back / forward)
  useEffect(() => {
    const onPop = () => {
      const s = readUrlState(window.location.search);
      if (s.datasetId && s.datasetId !== datasetId) return;   // App switches the dataset
      navMode.current = "skip";
      setFilters(s.filters);
      setDateFrom(s.dateFrom);
      setDateTo(s.dateTo);
      if (s.measure) setActiveMeasure(s.measure);
      setInspectCtx(s.inspect);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [datasetId]);

  // Esc leaves arrange mode — the usual way out of a transient editing mode
  useEffect(() => {
    if (!arranging) return;
    const onKey = (e) => { if (e.key === "Escape") setArranging(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [arranging]);

  // Ctrl/⌘ K (or "/" outside a text field) opens the command palette
  useEffect(() => {
    const onKey = (e) => {
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target?.tagName || "") || e.target?.isContentEditable;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      } else if (e.key === "/" && !typing && !e.ctrlKey && !e.metaKey && !e.altKey) {
        e.preventDefault();
        setPaletteOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

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
      // only fill in a measure if nothing has chosen one meanwhile: the saved
      // default view may have been applied while this request was in flight
      if (data.chosen_measure) setActiveMeasure((m) => m || data.chosen_measure);
    } catch (err) {
      setError(errorText(err, "Could not load the dashboard."));
    }
  }, [datasetId, filters, dateFrom, dateTo, activeMeasure]);

  useEffect(() => { load(); }, [load]);

  // driver / root-cause analysis, following the active measure
  useEffect(() => {
    getExplain(datasetId, activeMeasure || undefined)
      .then(setExplainData)
      .catch(() => setExplainData(null));
  }, [datasetId, activeMeasure]);

  const removeFilter = (dim) =>
    setFilters((prev) => {
      const next = { ...prev };
      delete next[dim];
      return next;
    });

  if (error) return <div className="empty-panel">{error}</div>;
  if (!dashboard) {
    // the shape of the page while it loads, so nothing jumps when it arrives
    return (
      <div className="dash-layout" aria-busy="true" aria-label="Loading the dashboard">
        <div className="dash-content">
          <div className="skeleton skeleton--title" />
          <div className="kpi-row">{[0, 1, 2].map((i) => <div key={i} className="skeleton skeleton--kpi" />)}</div>
          <div className="skeleton skeleton--chart" />
          <div className="chart-grid"><div className="skeleton skeleton--chart" /><div className="skeleton skeleton--chart" /></div>
        </div>
      </div>
    );
  }

  const subtypeOf = (m) => dashboard.kpis.find((k) => k.column === m)?.subtype;
  const measure = activeMeasure || dashboard.chosen_measure;
  const distNames = Object.keys(dashboard.distributions || {});

  // pick a geographic breakdown dimension (>=60% of its values are placeable)
  const geoEntry = Object.entries(dashboard.breakdowns || {}).find(
    ([, bd]) => (bd.data?.length || 0) >= 2 && mappableFraction((bd.data || []).map((d) => d.name)) >= 0.6
  );

  const activeFilterCount = Object.keys(filters).length + (dateFrom ? 1 : 0);

  // ---- drill-down: every number opens in the inspector ----
  // The slice starts from what the dashboard shows (its filters, dates and
  // measure); `partial` says which part of it was clicked.
  const openInspect = (partial = {}) => {
    if (!inspectCtx) returnFocus.current = document.activeElement;
    navMode.current = "push";
    setInspectCtx(makeCtx({ measure, filters, date_from: dateFrom || null, date_to: dateTo || null, ...partial }));
  };
  const inspectValue = (dim, value) => {
    if (value == null) return;
    openInspect({ filters: { ...filters, [dim]: String(value) } });
  };
  const inspectAll = (dim) => openInspect({ tab: "breakdown", dimension: dim });
  const navigateInspect = (next, { replace } = {}) => {
    navMode.current = replace ? "replace" : "push";
    setInspectCtx(next);
  };
  const closeInspect = () => {
    navMode.current = "push";
    setInspectCtx(null);
    const el = returnFocus.current;
    if (el && document.contains(el)) setTimeout(() => el.focus(), 0);
  };
  // "show this on the dashboard": the drilled slice becomes the dashboard's own
  const applyInspect = (c) => {
    navMode.current = "push";
    setFilters({ ...c.filters });
    setDateFrom(c.date_from || undefined);
    setDateTo(c.date_to || undefined);
    if (c.measure) setActiveMeasure(c.measure);
    setInspectCtx(null);
  };
  const investigate = (drill) => openInspect({
    measure: drill.measure || measure,
    filters: { ...filters, ...(drill.filters || {}) },
    ...(drill.period ? { date_from: drill.period, date_to: drill.period } : {}),
    ...(drill.dimension ? { tab: "breakdown", dimension: drill.dimension } : {}),
  });

  // ---- right-click: every way into the number under the pointer ----
  const pointAt = (e) => {
    if (e.clientX || e.clientY) return { x: e.clientX, y: e.clientY };
    // keyboard (Menu key / Shift+F10): anchor to the element instead
    const r = e.currentTarget?.getBoundingClientRect?.();
    return r ? { x: r.left + 12, y: r.bottom - 8 } : { x: 40, y: 40 };
  };
  const sliceMenu = (e, partial, title) => {
    const open = (extra) => () => openInspect({ ...partial, ...extra });
    const items = [
      { label: "Open details", hint: "trend · spread · parts", run: open({}) },
      ...(dashboard.date_column ? [{ label: "Why did it change?", hint: "waterfall", run: open({ tab: "change" }) }] : []),
      { label: "Break it down", run: open({ tab: "breakdown" }) },
      { label: "See the rows", run: open({ tab: "records" }) },
      { label: "Ask about it", run: open({ tab: "ask" }) },
    ];
    if (partial.filters || partial.date_from) {
      items.push({
        label: "Filter the dashboard to this",
        run: () => applyInspect(makeCtx({ measure, filters, date_from: dateFrom || null, date_to: dateTo || null, ...partial })),
      });
    }
    setMenu({ ...pointAt(e), title, items });
  };
  const segmentMenu = (e, dim, value) =>
    sliceMenu(e, { filters: { ...filters, [dim]: String(value) } }, `${humanLabel(dim)}: ${value}`);

  // Every section, in its natural order. A null node means "this dataset has
  // nothing to show here" — those drop out entirely so arrange mode never
  // offers an empty tile to drag.
  const allSections = [
    {
      key: "kpis",
      node: dashboard.kpis.length === 0 ? (
        <div className="empty-panel">
          No numeric measures detected in this dataset. Use “Review columns” to fix the roles.
        </div>
      ) : (
        <div className="kpi-row">
          {dashboard.kpis.map((kpi) => (
            <KpiCard key={kpi.column} kpi={kpi} active={kpi.column === measure}
              target={targetFor(targets, { measure: kpi.column, filters, date_from: dateFrom, date_to: dateTo })}
              onSelect={() => { setActiveMeasure(kpi.column); openInspect({ measure: kpi.column }); }}
              onContext={(e) => sliceMenu(e, { measure: kpi.column }, humanLabel(kpi.column))} />
          ))}
        </div>
      ),
    },
    {
      key: "actions",
      node: measure && (
        <ActionsPanel datasetId={datasetId} measure={measure} filters={filters}
          refreshKey={targetsVersion} onOpen={(evidence) => openInspect(evidence)} />
      ),
    },
    { key: "metrics", node: metrics.length > 0 && <CertifiedMetrics metrics={metrics} onInspect={openInspect} /> },
    {
      key: "drivers",
      // "what changed" compares the whole dataset's latest two months, so its
      // drill is that month alone — not the dashboard's filters
      node: <DriverAnalysis explain={explainData} onSelect={(dim, name, ex) => openInspect({
        measure: ex.measure, filters: { [dim]: String(name) },
        date_from: ex.current_period, date_to: ex.current_period,
      })} onContext={(e, dim, name, ex) => sliceMenu(e, {
        measure: ex.measure, filters: { [dim]: String(name) },
        date_from: ex.current_period, date_to: ex.current_period,
      }, `${humanLabel(dim)}: ${name} · ${ex.current_period}`)} />,
    },
    {
      key: "tree",
      node: measure && dashboard.date_column && (
        <DecompositionTree datasetId={datasetId} measure={measure} subtype={subtypeOf(measure)}
          filters={filters} dateFrom={dateFrom} dateTo={dateTo} onInspect={openInspect} />
      ),
    },
    { key: "growth", node: <GrowthStrip growth={dashboard.growth} measure={measure} /> },
    { key: "insights", node: <InsightsPanel insights={dashboard.insights} onInvestigate={investigate} /> },
    { key: "narrative", node: <AiNarrative datasetId={datasetId} /> },
    {
      key: "forecast",
      node: measure && (
        <ForecastChart
          measure={measure} subtype={subtypeOf(measure)}
          forecast={dashboard.forecasts?.[measure]}
          anomalies={dashboard.anomalies?.[measure]}
          onPeriod={(period) => openInspect({ date_from: period, date_to: period })}
          onContext={(e, period) => sliceMenu(e, { date_from: period, date_to: period }, `${humanLabel(measure)} · ${period}`)}
        />
      ),
    },
    {
      key: "breakdowns",
      node: (
        <div className="chart-grid">
          {Object.entries(dashboard.breakdowns).map(([dim, bd]) => (
            <BreakdownChart key={dim} dimensionName={dim} breakdown={bd}
              measure={measure} subtype={subtypeOf(measure)}
              onSelect={inspectValue} onShowAll={inspectAll} onContext={segmentMenu} activeValue={filters[dim]} />
          ))}
          {Object.entries(dashboard.breakdowns).slice(0, 1).map(([dim, bd]) => (
            <ContributionDonut key={`donut-${dim}`} dimensionName={dim} breakdown={bd}
              subtype={subtypeOf(measure)} onSelect={inspectValue} onShowAll={inspectAll} onContext={segmentMenu}
              activeValue={filters[dim]} />
          ))}
        </div>
      ),
    },
    {
      key: "map",
      node: geoEntry && (
        <MapChart dimensionName={geoEntry[0]} breakdown={geoEntry[1]}
          measure={measure} subtype={subtypeOf(measure)} />
      ),
    },
    {
      key: "pareto",
      node: dashboard.pareto && dashboard.pareto.total_categories > 2 && (
        <ParetoChart pareto={dashboard.pareto} onSelect={inspectValue} />
      ),
    },
    {
      key: "treemap",
      node: dashboard.treemap && <TreemapChart treemap={dashboard.treemap} subtype={subtypeOf(measure)} />,
    },
    {
      key: "correlations",
      node: dashboard.correlations && (() => {
        const scatterToShow = customScatter || dashboard.scatter;
        const activePair = scatterToShow ? { x: scatterToShow.x, y: scatterToShow.y } : null;
        return (
          <div className="chart-grid">
            <CorrelationHeatmap correlations={dashboard.correlations} activePair={activePair}
              onSelect={(x, y) => setPair({ x, y })} />
            <ScatterPlot scatter={scatterToShow} />
          </div>
        );
      })(),
    },
    {
      key: "distributions",
      node: distNames.length > 0 && (
        <div className="dist-section">
          <div className="section-title">Distribution of each measure</div>
          <div className="dist-grid">
            {distNames.map((name) => (
              <DistributionCard key={name} name={name} dist={dashboard.distributions[name]} />
            ))}
          </div>
        </div>
      ),
    },
    { key: "profile", node: <DataProfile profile={dashboard.data_profile} /> },
  ];

  const visible = orderSections(
    allSections.filter((s) => s.node && show(s.key)),
    sectionOrder
  );
  const visibleKeys = visible.map((s) => s.key);

  const commands = paletteOpen ? buildCommands({
    dashboard, views, visibleSections: visibleKeys, filters,
    on: {
      inspect: openInspect,
      applyView,
      scrollTo: (key) => document.getElementById(`section-${key}`)?.scrollIntoView({ behavior: "smooth", block: "start" }),
      clearFilters: () => { setFilters({}); setDateFrom(undefined); setDateTo(undefined); },
      setDates: (from, to) => { setDateFrom(from); setDateTo(to); },
      exportFile: (kind) => (kind === "csv" ? exportDatasetCsv(datasetId, dashboard.dataset?.name) : runExport(kind)),
      arrange: () => setArranging(true),
    },
  }) : [];

  return (
    <div className={`dash-layout${inspectCtx ? " has-inspector" : ""}`}>
      <div className="dash-content" ref={contentRef}>
        <header className="page-head page-head--dash">
          <div className="page-head__text">
            <h1 className="page-head__title">{dashboard.dataset?.name}</h1>
            <p className="page-head__sub">
              {dashboard.row_count_filtered?.toLocaleString("en-IN")} rows
              {datasetMeta && dashboard.row_count_filtered !== datasetMeta.row_count &&
                ` of ${Number(datasetMeta.row_count).toLocaleString("en-IN")}`}
              {dashboard.data_profile?.date_span?.to && <> · data up to {formatDate(dashboard.data_profile.date_span.to)}</>}
            </p>
          </div>
          {manageActions.length > 0 && (
            <Popover menu align="end" className="no-export" label="Manage" buttonClass="tb-btn"
              icon={<Icon name="settings" size={16} />}>
              {() => manageActions.map((a) => (
                <button key={a.label} role="menuitem" className="menu-item" onClick={a.run}>
                  <Icon name={a.icon} /> {a.label}
                </button>
              ))}
            </Popover>
          )}
        </header>

        <div className="toolbar-row no-export" data-tour="views" role="toolbar" aria-label="Dashboard controls">
          <ViewsBar
            views={views} activeViewId={activeViewId} dirty={viewDirty}
            onApply={applyView} onSave={saveView} onUpdate={updateActiveView} nameRequest={nameRequest}
          />
          <DateRangePresets
            dateSpan={dashboard.data_profile?.date_span}
            activeFrom={dateFrom}
            onApply={(from, to) => { setDateFrom(from); setDateTo(to); }}
            onClear={() => { setDateFrom(undefined); setDateTo(undefined); }}
          />
          <Popover align="start" className="filter-pop" title="Filters"
            icon={<Icon name="filter" size={16} />}
            label={<>Filter{activeFilterCount > 0 && <span className="tb-count">{activeFilterCount}</span>}</>}>
            {() => (
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
            )}
          </Popover>

          <div className="toolbar-row__spacer" />

          <button className="tb-btn palette-btn" onClick={() => setPaletteOpen(true)}
            aria-keyshortcuts={IS_MAC ? "Meta+K" : "Control+K"} title="Find any number, segment or action">
            <Icon name="search" size={16} /> Search <kbd>{IS_MAC ? "⌘K" : "Ctrl K"}</kbd>
          </button>
          <Popover menu align="end" title="More actions" buttonClass="tb-btn tb-btn--icon"
            icon={<Icon name="more" size={18} />} buttonProps={{ "aria-label": "More actions" }}>
            {() => (
              <>
                <div className="menu-label">This view</div>
                <button role="menuitem" className="menu-item" onClick={() => setNameRequest((n) => n + 1)}>
                  <Icon name="plus" /> Save as a new view…
                </button>
                {activeView && (
                  <>
                    <button role="menuitem" className="menu-item" onClick={setDefaultActiveView} disabled={activeView.is_default}>
                      <Icon name="layout" /> {activeView.is_default ? "Default view ★" : "Open this dataset on this view"}
                    </button>
                    <button role="menuitem" className="menu-item menu-item--danger" onClick={deleteActiveView}>
                      <Icon name="close" /> Delete this view
                    </button>
                  </>
                )}
                <button role="menuitem" className="menu-item" onClick={() => setArranging((a) => !a)}>
                  <Icon name="layout" /> {arranging ? "Finish arranging" : "Arrange sections"}
                </button>
                <div className="menu-sep" role="separator" />
                <div className="menu-label">Show sections</div>
                <div className="menu-checks">
                  {SECTIONS.map(([key, label]) => (
                    <button key={key} role="menuitemcheckbox" aria-checked={!hiddenSections.includes(key)}
                      className="menu-item menu-item--check" onClick={() => toggleSection(key)}>
                      <span className="menu-check" aria-hidden>{hiddenSections.includes(key) ? "" : "✓"}</span> {label}
                    </button>
                  ))}
                </div>
                <div className="menu-sep" role="separator" />
                <div className="menu-label">Export</div>
                <button role="menuitem" className="menu-item" onClick={() => runExport("pdf")} disabled={Boolean(exporting)}>
                  <Icon name="download" /> PDF
                </button>
                <button role="menuitem" className="menu-item" onClick={() => runExport("png")} disabled={Boolean(exporting)}>
                  <Icon name="download" /> PNG image
                </button>
                <button role="menuitem" className="menu-item" onClick={() => exportDatasetCsv(datasetId, dashboard.dataset?.name)}>
                  <Icon name="download" /> Data as CSV
                </button>
              </>
            )}
          </Popover>
        </div>

        {(Object.keys(filters).length > 0 || dateFrom || dateTo) && (
          <div className="active-scope no-export">
            {(dateFrom || dateTo) && (
              <button className="chip" onClick={() => { setDateFrom(undefined); setDateTo(undefined); }}
                title="Remove the date range">
                <Icon name="calendar" size={14} /> {formatRange(dateFrom, dateTo)} <span className="chip__x">×</span>
              </button>
            )}
            <FilterChips filters={filters} onRemove={removeFilter} onClearAll={() => setFilters({})} />
          </div>
        )}
        {exporting && <div className="export-busy no-export" role="status">Preparing {exporting.toUpperCase()}…</div>}

        {arranging && (
          <div className="arrange-hint no-export">
            <b>Arranging.</b> Drag a section by its bar, or use ↑ ↓ — then save the view to keep this layout.
            <button className="views-btn" onClick={resetArrangement}>Reset layout</button>
            <button className="views-btn views-btn--accent" onClick={() => setArranging(false)}>Done</button>
          </div>
        )}

        {visible.map(({ key, node }, i) => (
          <DashSection
            key={key} sectionKey={key} arranging={arranging}
            isFirst={i === 0} isLast={i === visible.length - 1}
            onReorder={reorderSection}
            onMove={(step) => stepSection(key, step, visibleKeys)}
            onHide={() => toggleSection(key)}
          >
            {node}
          </DashSection>
        ))}
      </div>

      <Suspense fallback={inspectCtx ? <aside className="inspector"><div className="skeleton skeleton--hero" /></aside> : null}>
      {inspectCtx && (
        <Inspector datasetId={datasetId} ctx={inspectCtx}
          onNavigate={navigateInspect} onClose={closeInspect} onApply={applyInspect}
          targets={targets} canEdit={canEdit} onTargetsChanged={targetsChanged} onRequestAlert={onRequestAlert} />
      )}
      {menu && <DataMenu {...menu} onClose={closeMenu} />}
      {paletteOpen && <CommandPalette commands={commands} onClose={() => setPaletteOpen(false)} />}
      </Suspense>
    </div>
  );
}
