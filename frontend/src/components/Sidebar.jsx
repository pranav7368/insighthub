import { useRef } from "react";
import Icon from "./Icon";
import Popover from "./Popover";

/**
 * The app's navigation: what you can do (bring in data), where you can go
 * (dashboard, compare, ask), which dataset you are on, and your workspace and
 * account. Collapses to an icon rail on narrow desktops and becomes a
 * slide-in drawer on phones.
 */
export default function Sidebar({
  tab, onTab, datasets, datasetId, onChooseDataset, canEdit, isAdmin,
  onUpload, onConnect, onTemplates, onTeam, onBilling, onApiKeys, onSecurity, onTour, onLogout,
  theme, onTheme, collapsed, onToggleCollapsed, mobileOpen, onCloseMobile, uploading,
}) {
  const fileRef = useRef(null);
  const structured = datasets.filter((d) => d.kind === "structured");
  const docs = datasets.filter((d) => d.kind !== "structured");
  const go = (fn) => () => { fn(); onCloseMobile(); };

  const navItem = (key, label, icon, extra = {}) => (
    <button key={key} className={`side-item${tab === key ? " is-active" : ""}`}
      aria-current={tab === key ? "page" : undefined} onClick={go(() => onTab(key))} title={label} {...extra}>
      <Icon name={icon} /><span className="side-item__label">{label}</span>
    </button>
  );

  return (
    <>
      {mobileOpen && <div className="side-scrim" onClick={onCloseMobile} aria-hidden />}
      <nav className={`sidebar${collapsed ? " is-collapsed" : ""}${mobileOpen ? " is-open" : ""}`}
        aria-label="Main">
        <div className="sidebar__brand">
          <span className="brand__logo" aria-hidden>◧</span>
          <span className="sidebar__name">InsightHub</span>
          <button className="side-icon-btn sidebar__collapse" onClick={onToggleCollapsed}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} title={collapsed ? "Expand" : "Collapse"}>
            <Icon name={collapsed ? "chevronRight" : "chevronLeft"} />
          </button>
          <button className="side-icon-btn sidebar__close" onClick={onCloseMobile} aria-label="Close menu">
            <Icon name="close" />
          </button>
        </div>

        <div className="sidebar__scroll">
          {canEdit && (
            <div className="side-group" aria-label="Bring in data" role="group">
              <div className="side-group__title">Data</div>
              <button className="side-item side-item--primary" data-tour="upload" title="Upload a file"
                onClick={() => fileRef.current?.click()} disabled={uploading}>
                <Icon name="upload" /><span className="side-item__label">{uploading ? "Uploading…" : "Upload a file"}</span>
              </button>
              <input ref={fileRef} type="file" hidden accept=".csv,.xlsx,.xlsm,.pdf,.docx,.txt,.md"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  e.target.value = "";
                  if (f) { onUpload(f); onCloseMobile(); }
                }} />
              <button className="side-item" data-tour="connect" onClick={go(onConnect)} title="Connect a live source">
                <Icon name="link" /><span className="side-item__label">Connect a source</span>
              </button>
              {structured.length > 0 && (
                <button className="side-item" data-tour="templates" onClick={go(onTemplates)} title="Industry templates">
                  <Icon name="template" /><span className="side-item__label">Templates</span>
                </button>
              )}
            </div>
          )}

          <div className="side-group" role="group" aria-label="Views">
            <div className="side-group__title">Analyse</div>
            {navItem("dashboard", "Dashboard", "dashboard")}
            {structured.length > 0 && navItem("compare", "Compare", "compare")}
            {navItem("ask", "Ask", "ask", { "data-tour": "ask" })}
          </div>

          {structured.length > 0 && (
            <div className="side-group" role="group" aria-label="Datasets">
              <div className="side-group__title">Datasets</div>
              {structured.map((d) => (
                <button key={d.dataset_id}
                  className={`side-item side-item--dataset${d.dataset_id === datasetId ? " is-active" : ""}`}
                  aria-current={d.dataset_id === datasetId ? "true" : undefined}
                  onClick={go(() => onChooseDataset(d.dataset_id))} title={`${d.name} — ${d.row_count} rows`}>
                  <Icon name="table" />
                  <span className="side-item__label">{d.name}</span>
                  <span className="side-item__meta">{Number(d.row_count).toLocaleString("en-IN")}</span>
                </button>
              ))}
              {docs.length > 0 && (
                <div className="side-note">
                  <Icon name="doc" size={14} /> {docs.length} document{docs.length > 1 ? "s" : ""} in Ask
                </div>
              )}
            </div>
          )}
        </div>

        <div className="sidebar__foot">
          {isAdmin && (
            <>
              <button className="side-item" onClick={go(onTeam)} title="Team"><Icon name="team" /><span className="side-item__label">Team</span></button>
              <button className="side-item" onClick={go(onBilling)} title="Billing"><Icon name="billing" /><span className="side-item__label">Billing</span></button>
              {onApiKeys && (
                <button className="side-item" onClick={go(onApiKeys)} title="API keys"><Icon name="key" /><span className="side-item__label">API keys</span></button>
              )}
            </>
          )}
          <Popover menu align="up" className="side-account" buttonClass="side-item"
            title="Account" icon={<Icon name="user" />} label={<span className="side-item__label">Account</span>}>
            {() => (
              <>
                <button role="menuitem" className="menu-item" onClick={onSecurity}><Icon name="shield" /> Account &amp; security</button>
                <div className="menu-sep" role="separator" />
                <div className="menu-label" id="theme-label">Theme</div>
                {[["light", "Light", "sun"], ["dark", "Dark", "moon"], ["auto", "Match system", "settings"]].map(([v, l, i]) => (
                  <button key={v} role="menuitemcheckbox" aria-checked={theme === v} className="menu-item"
                    onClick={() => onTheme(v)}>
                    <Icon name={i} /> {l}{theme === v && <span className="menu-item__check" aria-hidden>✓</span>}
                  </button>
                ))}
                <div className="menu-sep" role="separator" />
                <button role="menuitem" className="menu-item" onClick={onTour}><Icon name="help" /> Replay the tour</button>
                <button role="menuitem" className="menu-item" onClick={onLogout}><Icon name="logout" /> Log out</button>
              </>
            )}
          </Popover>
        </div>
      </nav>
    </>
  );
}
