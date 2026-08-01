import axios from "axios";

// Dev: talk to the backend on :8010 directly. In a container build we set
// VITE_API_BASE=/api and nginx proxies /api to the backend (same origin).
const client = axios.create({ baseURL: import.meta.env.VITE_API_BASE || "http://localhost:8010/api" });

// Attach the JWT on every request; the workspace is resolved server-side
// from this token, never from client-supplied data.
client.interceptors.request.use((cfg) => {
  const token = localStorage.getItem("ih_token");
  if (token) cfg.headers.Authorization = `Bearer ${token}`;
  return cfg;
});

// On 401, drop the stale token so the app falls back to the login screen.
client.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err?.response?.status === 401) localStorage.removeItem("ih_token");
    return Promise.reject(err);
  }
);

/**
 * A displayable message from an axios error.
 *
 * FastAPI answers a handled failure with a string `detail`, but a request that
 * fails schema validation (422) answers with a *list* of error objects —
 * rendering that straight into JSX throws "Objects are not valid as a React
 * child" and takes the page down. Always funnel API errors through here.
 */
export function errorText(err, fallback = "Something went wrong") {
  const detail = err?.response?.data?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail)) {
    const msgs = detail.map((d) => d?.msg).filter(Boolean);
    if (msgs.length) return msgs.join("; ");
  }
  return fallback;
}

export const signup = (email, password, workspace_name) =>
  client.post("/auth/signup", { email, password, workspace_name }).then((r) => r.data);

export const login = (email, password) =>
  client.post("/auth/login", { email, password }).then((r) => r.data);

export const listDatasets = () => client.get("/datasets").then((r) => r.data);

export const uploadDataset = (file) => {
  const form = new FormData();
  form.append("file", file);
  return client.post("/datasets/upload", form, {
    headers: { "Content-Type": "multipart/form-data" },
  }).then((r) => r.data);
};

export const loadSampleData = () => client.post("/datasets/sample").then((r) => r.data);

// --- Industry templates (dataset + certified metrics + arranged default view) ---
export const listTemplates = () => client.get("/templates").then((r) => r.data);

export const loadTemplate = (templateId) =>
  client.post("/datasets/template", { template_id: templateId }).then((r) => r.data);

export const exportDatasetCsv = (datasetId, name) =>
  client.get(`/datasets/${datasetId}/export.csv`, { responseType: "blob" }).then((r) => {
    const url = URL.createObjectURL(r.data);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${name || "dataset"}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  });

export const getSchema = (id) => client.get(`/datasets/${id}/schema`).then((r) => r.data);

export const overrideColumn = (id, col, role, subtype) =>
  client.patch(`/datasets/${id}/schema/${col}`, { role, subtype }).then((r) => r.data);

export const getDashboard = (id, params) =>
  client.get(`/datasets/${id}/dashboard`, { params }).then((r) => r.data);

export const ask = (question) => client.post("/ask", { question }).then((r) => r.data);

export const queryData = (datasetId, question) =>
  client.post(`/datasets/${datasetId}/query`, { question }).then((r) => r.data);

export const getScatter = (datasetId, params) =>
  client.get(`/datasets/${datasetId}/scatter`, { params }).then((r) => r.data);

export const getNarrative = (datasetId) =>
  client.post(`/datasets/${datasetId}/narrative`).then((r) => r.data);

export const getExplain = (datasetId, measure) =>
  client.get(`/datasets/${datasetId}/explain`, { params: measure ? { measure } : {} }).then((r) => r.data);

// --- Multi-table joins ---
export const suggestJoin = (left, right) =>
  client.get("/joins/suggest", { params: { left, right } }).then((r) => r.data);

export const listJoins = () => client.get("/joins").then((r) => r.data);

export const createJoin = (body) => client.post("/joins", body).then((r) => r.data);

export const rebuildJoin = (relationId) =>
  client.post(`/joins/${relationId}/rebuild`).then((r) => r.data);

export const deleteJoin = (relationId) =>
  client.delete(`/joins/${relationId}`).then((r) => r.data);

export const getQuality = (datasetId) =>
  client.get(`/datasets/${datasetId}/quality`).then((r) => r.data);

export const applyClean = (datasetId, action, column) =>
  client.post(`/datasets/${datasetId}/clean`, { action, column }).then((r) => r.data);

export const appendData = (id, file, mode) => {
  const form = new FormData();
  form.append("file", file);
  form.append("mode", mode);
  return client.post(`/datasets/${id}/append`, form, {
    headers: { "Content-Type": "multipart/form-data" },
  }).then((r) => r.data);
};

export const getBatches = (id) => client.get(`/datasets/${id}/batches`).then((r) => r.data);

export const rollbackBatch = (id, batchId) =>
  client.post(`/datasets/${id}/rollback`, { batch_id: batchId }).then((r) => r.data);

// --- Live data sources (connect a URL / Google Sheet that stays in sync) ---
export const listSources = () => client.get("/sources").then((r) => r.data);

export const createSource = (name, kind, url, refresh_interval_minutes) =>
  client.post("/sources", { name, kind, url, refresh_interval_minutes }).then((r) => r.data);

export const syncSource = (sourceId) =>
  client.post(`/sources/${sourceId}/sync`).then((r) => r.data);

export const deleteSource = (sourceId) =>
  client.delete(`/sources/${sourceId}`).then((r) => r.data);

// --- Saved & customizable dashboard views ---
export const listViews = (datasetId) =>
  client.get(`/datasets/${datasetId}/views`).then((r) => r.data);

export const createView = (datasetId, name, config, make_default = false) =>
  client.post(`/datasets/${datasetId}/views`, { name, config, make_default }).then((r) => r.data);

export const updateView = (viewId, patch) =>
  client.patch(`/views/${viewId}`, patch).then((r) => r.data);

export const deleteView = (viewId) =>
  client.delete(`/views/${viewId}`).then((r) => r.data);

// --- Public share links (read-only dashboard links) ---
export const listShares = (datasetId) =>
  client.get(`/datasets/${datasetId}/shares`).then((r) => r.data);

export const createShare = (datasetId, body) =>
  client.post(`/datasets/${datasetId}/shares`, body).then((r) => r.data);

export const revokeShare = (token) =>
  client.delete(`/shares/${token}`).then((r) => r.data);

// public: no auth required (the token is the capability)
export const getPublicDashboard = (token) =>
  client.get(`/public/${token}/dashboard`).then((r) => r.data);

// --- Threshold alerts (webhook delivery) ---
export const listAlerts = (datasetId) =>
  client.get(`/datasets/${datasetId}/alerts`).then((r) => r.data);

export const createAlert = (datasetId, body) =>
  client.post(`/datasets/${datasetId}/alerts`, body).then((r) => r.data);

export const setAlertEnabled = (alertId, enabled) =>
  client.patch(`/alerts/${alertId}`, { enabled }).then((r) => r.data);

export const testAlert = (alertId) =>
  client.post(`/alerts/${alertId}/test`).then((r) => r.data);

export const deleteAlert = (alertId) =>
  client.delete(`/alerts/${alertId}`).then((r) => r.data);

// --- Certified metrics (semantic layer) ---
export const listMetrics = (datasetId) =>
  client.get(`/datasets/${datasetId}/metrics`).then((r) => r.data);

export const createMetric = (datasetId, body) =>
  client.post(`/datasets/${datasetId}/metrics`, body).then((r) => r.data);

export const deleteMetric = (metricId) =>
  client.delete(`/metrics/${metricId}`).then((r) => r.data);

// --- Account security: two-factor, sessions, personal data ---
export const getMfaStatus = () => client.get("/auth/mfa").then((r) => r.data);

export const startMfaSetup = () => client.post("/auth/mfa/setup").then((r) => r.data);

export const enableMfa = (code) =>
  client.post("/auth/mfa/enable", { code }).then((r) => r.data);

export const disableMfa = (password) =>
  client.post("/auth/mfa/disable", { password }).then((r) => r.data);

export const revokeSessions = () =>
  client.post("/auth/revoke-sessions").then((r) => r.data);

export const downloadMyData = () =>
  client.get("/privacy/export/me", { responseType: "blob" }).then((r) => {
    const url = URL.createObjectURL(r.data);
    const a = document.createElement("a");
    a.href = url;
    a.download = "my-data.json";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  });

// --- Row-level security (admin) ---
export const listRlsRules = (datasetId) =>
  client.get(`/datasets/${datasetId}/rls`).then((r) => r.data);

export const createRlsRule = (datasetId, body) =>
  client.post(`/datasets/${datasetId}/rls`, body).then((r) => r.data);

export const deleteRlsRule = (ruleId) =>
  client.delete(`/rls/${ruleId}`).then((r) => r.data);

// --- PII masking policy (admin) ---
export const getPrivacy = (datasetId) =>
  client.get(`/datasets/${datasetId}/privacy`).then((r) => r.data);

export const setPrivacy = (datasetId, body) =>
  client.patch(`/datasets/${datasetId}/privacy`, body).then((r) => r.data);

// --- Team members & roles ---
export const listMembers = () => client.get("/members").then((r) => r.data);

export const addMember = (email, role, password) =>
  client.post("/members", { email, role, password: password || null }).then((r) => r.data);

export const updateMemberRole = (userId, role) =>
  client.patch(`/members/${userId}`, { role }).then((r) => r.data);

export const deleteMember = (userId) =>
  client.delete(`/members/${userId}`).then((r) => r.data);

export const changePassword = (oldPassword, newPassword) =>
  client.post("/auth/change-password", { old_password: oldPassword, new_password: newPassword }).then((r) => r.data);

// --- Billing / plans ---
export const getBilling = () => client.get("/billing").then((r) => r.data);

export const setBillingPlan = (plan) =>
  client.post("/billing/plan", { plan }).then((r) => r.data);

export const startCheckout = (plan) =>
  client.post("/billing/checkout", {
    plan,
    success_url: `${window.location.origin}/?billing=success`,
    cancel_url: `${window.location.origin}/?billing=cancel`,
  }).then((r) => r.data);
