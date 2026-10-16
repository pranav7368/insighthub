import { Suspense, lazy, useCallback, useEffect, useState } from "react";
import { getSchema, listDatasets, overrideColumn, uploadDataset } from "./api";
import Login from "./components/Login";
import UploadButton from "./components/UploadButton";
import Sidebar from "./components/Sidebar";
import Icon from "./components/Icon";
import TemplateGallery from "./components/TemplateGallery";
import DashboardView from "./components/DashboardView";
import TourOverlay from "./components/TourOverlay";
import Toaster from "./components/Toaster";
import { toast } from "./toast";
import { TOUR_KEY, TOUR_STEPS } from "./tour";
import { readUrlState } from "./drill";

// Loaded on first use: most sessions never open a dialog, Ask or Compare, so
// their code stays out of the first download.
const ConnectSource = lazy(() => import("./components/ConnectSource"));
const AccessDialog = lazy(() => import("./components/AccessDialog"));
const SecurityDialog = lazy(() => import("./components/SecurityDialog"));
const ShareDialog = lazy(() => import("./components/ShareDialog"));
const AlertsDialog = lazy(() => import("./components/AlertsDialog"));
const ReportsDialog = lazy(() => import("./components/ReportsDialog"));
const MetricsDialog = lazy(() => import("./components/MetricsDialog"));
const JoinDialog = lazy(() => import("./components/JoinDialog"));
const TeamDialog = lazy(() => import("./components/TeamDialog"));
const ApiKeysDialog = lazy(() => import("./components/ApiKeysDialog"));
const BillingDialog = lazy(() => import("./components/BillingDialog"));
const SchemaReview = lazy(() => import("./components/SchemaReview"));
const DataQuality = lazy(() => import("./components/DataQuality"));
const UpdateData = lazy(() => import("./components/UpdateData"));
const ComparePane = lazy(() => import("./components/ComparePane"));
const AskView = lazy(() => import("./components/AskView"));

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
  const [showAccess, setShowAccess] = useState(false);
  const [showSecurity, setShowSecurity] = useState(false);
  const [showApiKeys, setShowApiKeys] = useState(false);
  const [showShare, setShowShare] = useState(false);
  const [showAlerts, setShowAlerts] = useState(false);
  const [showReports, setShowReports] = useState(false);
  const [alertPreset, setAlertPreset] = useState(null);   // e.g. "alert me if this target falls behind"
  const [showMetrics, setShowMetrics] = useState(false);
  const [showJoin, setShowJoin] = useState(false);
  const [showTeam, setShowTeam] = useState(false);
  const [showBilling, setShowBilling] = useState(false);
  const [dashboardKey, setDashboardKey] = useState(0);  // bump to force dashboard reload after cleaning
  const [tourOn, setTourOn] = useState(false);
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("ih_sidebar") === "collapsed");
  const [mobileNav, setMobileNav] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [notice, setNotice] = useState(null);       // e.g. an upload that failed

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
      // a shared / bookmarked link names its dataset; otherwise take the first
      const wanted = readUrlState(window.location.search).datasetId;
      const structured = list.find((d) => d.kind === "structured" && d.dataset_id === wanted)
        || list.find((d) => d.kind === "structured");
      if (structured) setDatasetId(structured.dataset_id);
    });
  }, [authed, refresh]);

  // back / forward across a dataset switch
  useEffect(() => {
    const onPop = () => {
      const id = readUrlState(window.location.search).datasetId;
      if (id && id !== datasetId && datasets.some((d) => d.dataset_id === id)) {
        setDatasetId(id);
        setTab("dashboard");
      }
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [datasetId, datasets]);

  const chooseDataset = (id) => {
    window.history.pushState(null, "", `${window.location.pathname}?ds=${encodeURIComponent(id)}`);
    setDatasetId(id);
  };

  const handleUpload = async (file) => {
    const result = await uploadDataset(file);
    const list = await refresh();
    toast(`Uploaded “${result.name || file.name}”`
      + (result.row_count ? ` · ${Number(result.row_count).toLocaleString("en-IN")} rows` : ""));
    if (result.kind === "structured") {
      setDatasetId(result.dataset_id);
      setTab("dashboard");
    } else {
      setTab("ask");
    }
    return list;
  };
  // the sidebar's upload: same flow, with its own busy state and error banner
  const uploadFromSidebar = async (file) => {
    setUploading(true);
    setNotice(null);
    try { await handleUpload(file); }
    catch (err) { setNotice(err?.response?.data?.detail || "Upload failed. Check the file and try again."); }
    finally { setUploading(false); }
  };
  const toggleCollapsed = () => setCollapsed((c) => {
    localStorage.setItem("ih_sidebar", c ? "expanded" : "collapsed");
    return !c;
  });

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

  if (!authed) return <Login onAuthed={(r) => { setAuthed(true); setRole(r || "admin"); }} />;

  const structuredDatasets = datasets.filter((d) => d.kind === "structured");

  // dataset actions, shown in the dashboard's own header
  const manageActions = canEdit ? [
    { label: "Certified metrics", icon: "dashboard", run: () => setShowMetrics(true) },
    ...(structuredDatasets.length >= 2 ? [{ label: "Link datasets", icon: "link", run: () => setShowJoin(true) }] : []),
    { label: "Share dashboard", icon: "link", run: () => setShowShare(true) },
    { label: "Alerts", icon: "help", run: () => setShowAlerts(true) },
    { label: "Email reports", icon: "doc", run: () => setShowReports(true) },
    ...(isAdmin ? [{ label: "Access & privacy", icon: "shield", run: () => setShowAccess(true) }] : []),
    { label: "Update data", icon: "upload", run: () => setShowUpdate(true) },
    { label: "Review columns", icon: "table", run: openSchema },
    { label: "Data quality", icon: "filter", run: () => setShowQuality(true) },
  ] : [];
  const pageTitle = { compare: "Compare", ask: "Ask" }[tab];

  return (
    <div className={`app-shell app-shell--side${collapsed ? " is-collapsed" : ""}`}>
      <Sidebar
        tab={tab} onTab={setTab} datasets={datasets} datasetId={datasetId}
        onChooseDataset={(id) => { chooseDataset(id); setTab("dashboard"); }}
        canEdit={canEdit} isAdmin={isAdmin} uploading={uploading}
        onUpload={uploadFromSidebar} onConnect={() => setShowConnect(true)} onTemplates={() => setShowTemplates(true)}
        onTeam={() => setShowTeam(true)} onBilling={() => setShowBilling(true)}
        onApiKeys={() => setShowApiKeys(true)}
        onSecurity={() => setShowSecurity(true)} onTour={() => setTourOn(true)} onLogout={logout}
        theme={theme} onTheme={setTheme}
        collapsed={collapsed} onToggleCollapsed={toggleCollapsed}
        mobileOpen={mobileNav} onCloseMobile={() => setMobileNav(false)}
      />

      <div className="app-main">
        {/* phones: the sidebar becomes a drawer behind this bar */}
        <header className="mobile-bar">
          <button className="side-icon-btn" onClick={() => setMobileNav(true)} aria-label="Open menu">
            <Icon name="menu" />
          </button>
          <span className="brand"><span className="brand__logo" aria-hidden>◧</span> InsightHub</span>
        </header>

        {notice && (
          <div className="app-notice" role="alert">
            {notice}
            <button className="side-icon-btn" onClick={() => setNotice(null)} aria-label="Dismiss"><Icon name="close" size={16} /></button>
          </div>
        )}

        <main className="main">
          {pageTitle && (
            <div className="page-head">
              <h1 className="page-head__title">{pageTitle}</h1>
              <p className="page-head__sub">
                {tab === "compare" ? "Put two segments or two periods side by side."
                  : "Ask your data or your documents in plain English — every answer shows the query behind it."}
              </p>
            </div>
          )}
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
              datasetId && <DashboardView key={`${datasetId}-${dashboardKey}`} datasetId={datasetId} canEdit={canEdit}
                manageActions={manageActions}
                datasetMeta={structuredDatasets.find((d) => d.dataset_id === datasetId)}
                onRequestAlert={(preset) => { setAlertPreset(preset); setShowAlerts(true); }} />
            )
          )}
          <Suspense fallback={<div className="empty-panel">Loading…</div>}>
            {tab === "compare" && datasetId && <ComparePane key={datasetId} datasetId={datasetId} />}
            {tab === "ask" && <AskView datasetId={datasetId} hasStructured={structuredDatasets.length > 0} />}
          </Suspense>
        </main>
      </div>

      <Suspense fallback={null}>
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
      {showReports && datasetId && <ReportsDialog datasetId={datasetId} onClose={() => setShowReports(false)} />}
      {showAlerts && datasetId && (
        <AlertsDialog datasetId={datasetId} preset={alertPreset}
          onClose={() => { setShowAlerts(false); setAlertPreset(null); }} />
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
      {showAccess && datasetId && (
        <AccessDialog
          datasetId={datasetId}
          datasetName={structuredDatasets.find((d) => d.dataset_id === datasetId)?.name || "dataset"}
          onClose={() => setShowAccess(false)}
        />
      )}
      {showSecurity && (
        <SecurityDialog
          onClose={() => setShowSecurity(false)}
          onSignedOut={logout}
        />
      )}
      {showTeam && <TeamDialog onClose={() => setShowTeam(false)} />}
      {showApiKeys && <ApiKeysDialog onClose={() => setShowApiKeys(false)} />}
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
      </Suspense>
      {tourOn && <TourOverlay steps={TOUR_STEPS} onFinish={endTour} />}
      <Toaster />
    </div>
  );
}
