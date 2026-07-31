import { useEffect, useState } from "react";
import { getBilling, setBillingPlan, startCheckout } from "../api";

const RESOURCES = [
  ["datasets", "Datasets"],
  ["members", "Team members"],
  ["alerts", "Alerts"],
];

function UsageBar({ label, used, limit }) {
  const pct = limit ? Math.min(100, (used / limit) * 100) : 0;
  const over = limit != null && used >= limit;
  return (
    <div className="bill-usage">
      <div className="bill-usage__head">
        <span>{label}</span>
        <span className={over ? "bill-usage__count bill-usage__count--over" : "bill-usage__count"}>
          {used}{limit == null ? " / ∞" : ` / ${limit}`}
        </span>
      </div>
      <div className="bill-usage__track">
        <div className={`bill-usage__bar${over ? " bill-usage__bar--over" : ""}`}
          style={{ width: `${limit == null ? 6 : pct}%` }} />
      </div>
    </div>
  );
}

export default function BillingDialog({ onClose }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = () => getBilling().then(setData).catch(() => setError("Could not load billing."));
  useEffect(() => { load(); }, []);

  const upgrade = async () => {
    setBusy(true); setError(null);
    try {
      const { url } = await startCheckout("pro");
      if (url) window.location.href = url;
    } catch (err) {
      // Stripe not configured — offer the manual/self-hosted path
      setError(err?.response?.data?.detail || "Checkout is unavailable.");
    } finally {
      setBusy(false);
    }
  };

  const setPlan = async (plan) => {
    setBusy(true); setError(null);
    try { await setBillingPlan(plan); load(); }
    catch (err) { setError(err?.response?.data?.detail || "Could not change the plan."); }
    finally { setBusy(false); }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal__header">
          <h3>Plan & billing</h3>
          <button onClick={onClose}>Close</button>
        </div>

        {!data ? (
          <div className="empty-panel">{error || "Loading…"}</div>
        ) : !data.billing_enabled ? (
          <p className="modal__hint">
            Billing isn’t enabled on this deployment — <b>all features are unlimited</b>. To run InsightHub
            as a paid SaaS, set <code>IH_BILLING_ENABLED=1</code> (and Stripe keys) on the server.
          </p>
        ) : (
          <>
            <div className="bill-plan">
              <span className={`bill-badge bill-badge--${data.plan}`}>{data.limits.label} plan</span>
              {data.subscription.status !== "active" && (
                <span className="bill-status">· {data.subscription.status}</span>
              )}
            </div>

            <div className="bill-usages">
              {RESOURCES.map(([key, label]) => (
                <UsageBar key={key} label={label} used={data.usage[key]} limit={data.limits[key]} />
              ))}
            </div>

            {error && <div className="dq-error">{error}</div>}

            {data.plan === "free" ? (
              <div className="bill-actions">
                <button className="src-connect" onClick={upgrade} disabled={busy}>
                  {busy ? "…" : "Upgrade to Pro"}
                </button>
                <button className="views-btn" onClick={() => setPlan("pro")} disabled={busy}
                  title="Set the plan directly (self-hosted, no Stripe)">
                  Set Pro manually
                </button>
              </div>
            ) : (
              <div className="bill-actions">
                <span className="bill-thanks">You’re on Pro — thank you.</span>
                <button className="views-btn" onClick={() => setPlan("free")} disabled={busy}>Downgrade to Free</button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
