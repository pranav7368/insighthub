import { useCallback, useEffect, useState } from "react";
import { getSchema, listDatasets, overrideColumn, uploadDataset } from "./api";
import Login from "./components/Login";
import UploadButton from "./components/UploadButton";
import ConnectSource from "./components/ConnectSource";
import TemplateGallery from "./components/TemplateGallery";
import ShareDialog from "./components/ShareDialog";
import AlertsDialog from "./components/AlertsDialog";
import MetricsDialog from "./components/MetricsDialog";
import JoinDialog from "./components/JoinDialog";
import TeamDialog from "./components/TeamDialog";
import BillingDialog from "./components/BillingDialog";
import SchemaReview from "./components/SchemaReview";
import DataQuality from "./components/DataQuality";
import UpdateData from "./components/UpdateData";
import DashboardView from "./components/DashboardView";
import ComparePane from "./components/ComparePane";
import AskView from "./components/AskView";
import TourOverlay from "./components/TourOverlay";
import { TOUR_KEY, TOUR_STEPS } from "./tour";

function useTheme() {
  const [theme, setTheme] = useState(() => localStorage.getItem("ih_theme") || "auto");
  useEffect(() => {
    if (theme === "auto") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("ih_theme", theme);
  }, [theme]);
  return [theme, setTheme];
}

export default function App() {
  const [authed, setAuthed] = useState(() => Boolean(localStorage.getItem("ih_token")));
  const [role, setRole] = useState(() => localStorage.getItem("ih_role") || "admin");
  const [theme, setTheme] = useTheme();
  const [tab, setTab] = useState("dashboard");
  const [datasets, setDatasets] = useState([]);
  const [datasetId, setDatasetId] = useState(null);
  const [showSchema, setShowSchema] = useState(false);
  const [schemaCols, setSchemaCols] = useState([]);
  const [showQuality, setShowQuality] = useState(false);
  const [showUpdate, setShowUpdate] = useState(false);
  const [showConnect, setShowConnect] = useState(false);
  const [showTemplates, setShowTemplates] = useState(false);
  const [showShare, setShowShare] = useState(false);
  const [showAlerts, setShowAlerts] = useState(false);
  const [showMetrics, setShowMetrics] = useState(false);
  const [showJoin, setShowJoin] = useState(false);
  const [showTeam, setShowTeam] = useState(false);
  const [showBilling, setShowBilling] = useState(false);
  const [dashboardKey, setDashboardKey] = useState(0);  // bump to force dashboard reload after cleaning
  const [tourOn, setTourOn] = useState(false);

  const canEdit = role === "admin" || role === "editor";
  const isAdmin = role === "admin";

  // First run: show the tour once the shell has mounted, so its anchors exist.
  useEffect(() => {
    if (!authed || localStorage.getItem(TOUR_KEY)) return;
    const t = setTimeout(() => setTourOn(true), 400);
    return () => clearTimeout(t);
  }, [authed]);

  const endTour = () => {
    localStorage.setItem(TOUR_KEY, "done");
    setTourOn(false);
  };

  const refresh = useCallback(async () => {
    const list = await listDatasets();
    setDatasets(list);
    return list;
  }, []);

  useEffect(() => {
    if (!authed) return;
    refresh().then((list) => {
      const structured = list.find((d) => d.kind === "structured");
      if (structured) setDatasetId(structured.dataset_id);
    });
  }, [authed, refresh]);

  const handleUpload = async (file) => {
    const result = await uploadDataset(file);
    const list = await refresh();
    if (result.kind === "structured") {
      setDatasetId(result.dataset_id);
      setTab("dashboard");
    } else {
      setTab("ask");
    }
    return list;
  };

  const handleConnected = async (newDatasetId) => {
    await refresh();
    if (newDatasetId) {
      setDatasetId(newDatasetId);
      setTab("dashboard");
    }
    setDashboardKey((k) => k + 1);
  };

  const openSchema = async () => {
    if (!datasetId) return;
    setSchemaCols(await getSchema(datasetId));
    setShowSchema(true);
  };

  const handleOverride = async (col, role, subtype) => {
    await overrideColumn(datasetId, col, role, subtype);
    setSchemaCols(await getSchema(datasetId));
  };

  const logout = () => {
    localStorage.removeItem("ih_token");
    localStorage.removeItem("ih_role");
    setAuthed(false);
    setDatasets([]);
    setDatasetId(null);
  };

  // run a Manage-menu action and close the <details> dropdown
  const runFromMenu = (fn) => (e) => {
    e.currentTarget.closest("details")?.removeAttribute("open");
    fn();
  };

  if (!authed) return <Login onAuthed={(r) => { setAuthed(true); setRole(r || "admin"); }} />;

  const structuredDatasets = datasets.filter((d) => d.kind === "structured");

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand"><span className="brand__logo">◧</span> InsightHub</div>
        <nav className="tabs" aria-label="Primary">
          <button className={tab === "dashboard" ? "active" : ""} onClick={() => setTab("dashboard")}>Dashboard</button>
          {structuredDatasets.length > 0 && (
            <button className={tab === "compare" ? "active" : ""} onClick={() => setTab("compare")}>Compare</button>
          )}
          <button data-tour="ask" className={tab === "ask" ? "active" : ""} onClick={() => setTab("ask")}>Ask</button>
        </nav>
        <div className="app-header__actions">
          {canEdit && structuredDatasets.length > 0 && (
            <button className="ghost-btn" data-tour="templates" onClick={() => setShowTemplates(true)}>Templates</button>
          )}
          {canEdit && (
            <button className="ghost-btn" data-tour="connect" onClick={() => setShowConnect(true)}>Connect source</button>
          )}
          {canEdit && <span data-tour="upload"><UploadButton onUpload={handleUpload} /></span>}
          {isAdmin && <button className="ghost-btn" onClick={() => setShowTeam(true)}>Team</button>}
          {isAdmin && <button className="ghost-btn" onClick={() => setShowBilling(true)}>Billing</button>}
          <button className="icon-btn" title={`Theme: ${theme}`} aria-label="Toggle theme"
            onClick={() => setTheme(theme === "dark" ? "light" : theme === "light" ? "auto" : "dark")}>
            {theme === "dark" ? "☾" : theme === "light" ? "☀" : "◐"}
          </button>
          <button className="icon-btn" title="Replay the product tour" aria-label="Replay the product tour"
            onClick={() => setTourOn(true)}>?</button>
          <button className="ghost-btn" onClick={logout}>Log out</button>
        </div>
      </header>

      {(tab === "dashboard" || tab === "compare") && structuredDatasets.length > 0 && (
        <div className="toolbar">
          <select className="dataset-select" value={datasetId ?? ""} onChange={(e) => setDatasetId(e.target.value)}>
            {structuredDatasets.map((d) => (
              <option key={d.dataset_id} value={d.dataset_id}>{d.name} ({d.row_count} rows)</option>
            ))}
          </select>
          {tab === "dashboard" && datasetId && canEdit && (
            <details className="menu">
              <summary className="menu__btn">Manage <span aria-hidden>▾</span></summary>
              <div className="menu__list" role="menu">
                <button role="menuitem" onClick={runFromMenu(() => setShowMetrics(true))}>Certified metrics</button>
                {structuredDatasets.length >= 2 && (
                  <button role="menuitem" onClick={runFromMenu(() => setShowJoin(true))}>Link datasets</button>
                )}
                <button role="menuitem" onClick={runFromMenu(() => setShowShare(true))}>Share dashboard</button>
                <button role="menuitem" onClick={runFromMenu(() => setShowAlerts(true))}>Alerts</button>
                <button role="menuitem" onClick={runFromMenu(() => setShowUpdate(true))}>Update data</button>
                <button role="menuitem" onClick={runFromMenu(openSchema)}>Review columns</button>
                <button role="menuitem" onClick={runFromMenu(() => setShowQuality(true))}>Data quality</button>
              </div>
            </details>
          )}
        </div>
      )}

      <main className="main">
        {tab === "dashboard" && (
          structuredDatasets.length === 0 ? (
            <div className="empty-state">
              <h2>No spreadsheet data yet</h2>
              <p>{canEdit
                ? "Upload a CSV or Excel file — the dashboard builds itself. Or connect a Google Sheet / CSV link that stays in sync. Upload a PDF or Word document to ask questions about it in the “Ask” tab."
                : "No dashboards have been added to this workspace yet. Ask an admin or editor to upload data or connect a source."}</p>
              {canEdit && (
                <>
                  <div className="empty-state__actions">
                    <UploadButton onUpload={handleUpload} label="Upload your data" primary />
                    <button className="ghost-btn" onClick={() => setShowConnect(true)}>Connect a Google Sheet</button>
                  </div>
                  <div className="empty-state__divider"><span>or explore an industry template</span></div>
                  <div className="tpl-anchor" data-tour="templates">
                    <TemplateGallery onLoaded={handleConnected} />
                  </div>
                </>
              )}
            </div>
          ) : (
            datasetId && <DashboardView key={`${datasetId}-${dashboardKey}`} datasetId={datasetId} />
          )
        )}
        {tab === "compare" && datasetId && <ComparePane key={datasetId} datasetId={datasetId} />}
        {tab === "ask" && <AskView datasetId={datasetId} hasStructured={structuredDatasets.length > 0} />}
      </main>

      {showConnect && (
        <ConnectSource
          onClose={() => setShowConnect(false)}
          onConnected={handleConnected}
        />
      )}
      {showTemplates && (
        <TemplateGallery
          compact
          onLoaded={handleConnected}
          onClose={() => setShowTemplates(false)}
        />
      )}
      {showShare && datasetId && (
        <ShareDialog datasetId={datasetId} onClose={() => setShowShare(false)} />
      )}
      {showAlerts && datasetId && (
        <AlertsDialog datasetId={datasetId} onClose={() => setShowAlerts(false)} />
      )}
      {showMetrics && datasetId && (
        <MetricsDialog
          datasetId={datasetId}
          onClose={() => setShowMetrics(false)}
          onChanged={() => setDashboardKey((k) => k + 1)}
        />
      )}
      {showJoin && (
        <JoinDialog
          datasets={structuredDatasets}
          currentDatasetId={datasetId}
          onClose={() => setShowJoin(false)}
          onCreated={(newId) => { handleConnected(newId); setShowJoin(false); }}
        />
      )}
      {showTeam && <TeamDialog onClose={() => setShowTeam(false)} />}
      {showBilling && <BillingDialog onClose={() => setShowBilling(false)} />}
      {showSchema && (
        <SchemaReview columns={schemaCols} onOverride={handleOverride} onClose={() => setShowSchema(false)} />
      )}
      {showQuality && datasetId && (
        <DataQuality
          datasetId={datasetId}
          onClose={() => setShowQuality(false)}
          onChanged={() => { refresh(); setDashboardKey((k) => k + 1); }}
        />
      )}
      {showUpdate && datasetId && (
        <UpdateData
          datasetId={datasetId}
          datasetName={structuredDatasets.find((d) => d.dataset_id === datasetId)?.name || "dataset"}
          onClose={() => setShowUpdate(false)}
          onChanged={() => { refresh(); setDashboardKey((k) => k + 1); }}
        />
      )}
      {tourOn && <TourOverlay steps={TOUR_STEPS} onFinish={endTour} />}
    </div>
  );
}
