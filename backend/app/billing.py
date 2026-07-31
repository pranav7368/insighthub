"""Plans, entitlements, and subscription state.

Plan gating is OPT-IN (IH_BILLING_ENABLED). When off — the default, and how
self-hosted installs run — every workspace is unlimited. When on, a free
workspace is capped and an active paid subscription (managed via Stripe, or set
manually by an admin) lifts the caps. Quota is checked at the create points for
datasets, members, and alerts, so `check_quota` is a no-op when billing is off.
"""

from .core import config

PLANS = {
    "free": {"label": "Free", "datasets": 2, "members": 3, "alerts": 2, "scheduled_refresh": False},
    "pro":  {"label": "Pro",  "datasets": None, "members": None, "alerts": None, "scheduled_refresh": True},
}
ACTIVE_STATUSES = ("active", "trialing")
_RESOURCES = ("datasets", "members", "alerts")


class BillingError(ValueError):
    """A billing operation failed (bad plan, Stripe not configured, …)."""


class QuotaError(BillingError):
    """A plan limit was reached — the caller should surface an upgrade prompt."""


def get_subscription(con, workspace_id: str) -> dict:
    row = con.execute(
        "SELECT plan, status, stripe_customer_id, stripe_subscription_id, current_period_end "
        "FROM subscriptions WHERE workspace_id = ?", [workspace_id],
    ).fetchone()
    if row is None:
        plan, status, cust, subid, end = "free", "active", None, None, None
    else:
        plan, status, cust, subid, end = row
    if plan not in PLANS:
        plan = "free"
    effective = plan if status in ACTIVE_STATUSES else "free"
    return {
        "plan": plan, "status": status, "effective_plan": effective,
        "stripe_customer_id": cust, "stripe_subscription_id": subid,
        "current_period_end": str(end) if end else None,
    }


def set_plan(con, workspace_id: str, plan: str, status: str = "active",
             stripe_customer_id=None, stripe_subscription_id=None, current_period_end=None) -> dict:
    if plan not in PLANS:
        raise BillingError("unknown plan")
    exists = con.execute("SELECT 1 FROM subscriptions WHERE workspace_id = ?", [workspace_id]).fetchone()
    if exists:
        con.execute(
            "UPDATE subscriptions SET plan = ?, status = ?, "
            "stripe_customer_id = coalesce(?, stripe_customer_id), "
            "stripe_subscription_id = coalesce(?, stripe_subscription_id), "
            "current_period_end = coalesce(?, current_period_end), updated_at = current_timestamp "
            "WHERE workspace_id = ?",
            [plan, status, stripe_customer_id, stripe_subscription_id, current_period_end, workspace_id],
        )
    else:
        con.execute(
            "INSERT INTO subscriptions "
            "(workspace_id, plan, status, stripe_customer_id, stripe_subscription_id, current_period_end) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [workspace_id, plan, status, stripe_customer_id, stripe_subscription_id, current_period_end],
        )
    return get_subscription(con, workspace_id)


def usage(con, workspace_id: str) -> dict:
    def count(table):
        return con.execute(f"SELECT count(*) FROM {table} WHERE workspace_id = ?", [workspace_id]).fetchone()[0]
    return {"datasets": count("datasets"), "members": count("users"), "alerts": count("alerts")}


def entitlements(con, workspace_id: str) -> dict:
    sub = get_subscription(con, workspace_id)
    plan = sub["effective_plan"]
    return {
        "billing_enabled": config.BILLING_ENABLED,
        "subscription": sub,
        "plan": plan,
        "limits": PLANS[plan],
        "usage": usage(con, workspace_id),
        "plans": {k: {kk: vv for kk, vv in v.items()} for k, v in PLANS.items()},
    }


def check_quota(con, workspace_id: str, resource: str) -> None:
    """Raise QuotaError if creating one more `resource` would exceed the plan.
    No-op unless billing is enabled."""
    if not config.BILLING_ENABLED:
        return
    plan = get_subscription(con, workspace_id)["effective_plan"]
    limit = PLANS[plan].get(resource)
    if limit is None:  # unlimited
        return
    if usage(con, workspace_id).get(resource, 0) >= limit:
        raise QuotaError(
            f"your {PLANS[plan]['label']} plan is limited to {limit} {resource} — upgrade to add more"
        )
