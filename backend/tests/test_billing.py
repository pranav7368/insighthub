"""Billing: plans, quota gating, subscription state machine, Stripe webhook."""

import pytest

from app import billing_stripe
from app.billing import (
    BillingError, QuotaError, check_quota, entitlements, get_subscription,
    set_plan, usage,
)
from app.core import config


@pytest.fixture()
def ws(con):
    con.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws_a', 'A')")
    return con, "ws_a"


@pytest.fixture()
def billing_on(monkeypatch):
    monkeypatch.setattr(config, "BILLING_ENABLED", True)


def _add_datasets(con, workspace_id, n):
    for i in range(n):
        con.execute(
            "INSERT INTO datasets (dataset_id, workspace_id, name, source_file, kind) "
            "VALUES (?, ?, ?, ?, 'structured')", [f"ds_{i}", workspace_id, f"d{i}", "f.csv"])


# --------------------------------------------------------- defaults --------

def test_absent_subscription_is_free_active(ws):
    con, wsid = ws
    sub = get_subscription(con, wsid)
    assert sub["plan"] == "free" and sub["effective_plan"] == "free" and sub["status"] == "active"


def test_quota_is_noop_when_billing_disabled(ws):
    con, wsid = ws
    _add_datasets(con, wsid, 10)          # well over the free cap
    check_quota(con, wsid, "datasets")     # billing off → no raise


# --------------------------------------------------------- quota -----------

def test_free_dataset_cap_enforced(ws, billing_on):
    con, wsid = ws
    _add_datasets(con, wsid, 2)            # free cap is 2
    with pytest.raises(QuotaError):
        check_quota(con, wsid, "datasets")


def test_pro_lifts_the_cap(ws, billing_on):
    con, wsid = ws
    _add_datasets(con, wsid, 5)
    set_plan(con, wsid, "pro")
    check_quota(con, wsid, "datasets")     # unlimited → no raise


def test_canceled_pro_falls_back_to_free(ws, billing_on):
    con, wsid = ws
    set_plan(con, wsid, "pro", status="canceled")
    assert get_subscription(con, wsid)["effective_plan"] == "free"
    _add_datasets(con, wsid, 2)
    with pytest.raises(QuotaError):
        check_quota(con, wsid, "datasets")


def test_entitlements_shape(ws, billing_on):
    con, wsid = ws
    _add_datasets(con, wsid, 1)
    ent = entitlements(con, wsid)
    assert ent["plan"] == "free" and ent["limits"]["datasets"] == 2
    assert ent["usage"]["datasets"] == 1 and ent["billing_enabled"] is True


# --------------------------------------------- Stripe state machine --------

def test_set_plan_rejects_unknown(ws):
    con, wsid = ws
    with pytest.raises(BillingError):
        set_plan(con, wsid, "enterprise")


def test_webhook_checkout_upgrades(ws):
    con, wsid = ws
    event = {"type": "checkout.session.completed",
             "data": {"object": {"client_reference_id": wsid, "customer": "cus_1",
                                  "subscription": "sub_1", "metadata": {"plan": "pro"}}}}
    out = billing_stripe.apply_event(con, event)
    assert out["workspace_id"] == wsid
    sub = get_subscription(con, wsid)
    assert sub["plan"] == "pro" and sub["stripe_subscription_id"] == "sub_1"


def test_webhook_subscription_deleted_downgrades(ws):
    con, wsid = ws
    set_plan(con, wsid, "pro", stripe_subscription_id="sub_9")
    event = {"type": "customer.subscription.deleted", "data": {"object": {"id": "sub_9"}}}
    billing_stripe.apply_event(con, event)
    sub = get_subscription(con, wsid)
    assert sub["plan"] == "free" and sub["status"] == "canceled"


def test_webhook_unknown_subscription_is_ignored(ws):
    con, wsid = ws
    event = {"type": "customer.subscription.deleted", "data": {"object": {"id": "sub_unknown"}}}
    assert billing_stripe.apply_event(con, event)["handled"] is None


def test_checkout_requires_stripe_config(monkeypatch):
    monkeypatch.setattr(config, "STRIPE_SECRET_KEY", "")
    with pytest.raises(BillingError):
        billing_stripe.create_checkout("ws_a", "pro", None, "http://ok", "http://no")
