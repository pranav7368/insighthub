"""Stripe boundary — checkout sessions and webhook processing.

Stripe is optional: the SDK is imported lazily and only when a key is set, so
the app runs fine without it (self-hosted / offline). The webhook handler
updates the workspace's subscription from Stripe events; in dev/test (no webhook
secret) it accepts unsigned JSON so the state machine can be exercised without a
live Stripe account.
"""

import json

from .billing import BillingError, set_plan
from .core import config


def _stripe():
    if not config.STRIPE_SECRET_KEY:
        raise BillingError("Stripe is not configured (set IH_STRIPE_SECRET_KEY)")
    try:
        import stripe
    except ImportError:
        raise BillingError("the 'stripe' package is not installed (pip install stripe)")
    stripe.api_key = config.STRIPE_SECRET_KEY
    return stripe


def create_checkout(workspace_id: str, plan: str, email: str | None,
                    success_url: str, cancel_url: str) -> dict:
    price = config.STRIPE_PRICES.get(plan)
    if not price:
        raise BillingError(f"no Stripe price configured for the {plan!r} plan")
    stripe = _stripe()
    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price, "quantity": 1}],
        client_reference_id=workspace_id,
        customer_email=email,
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"workspace_id": workspace_id, "plan": plan},
    )
    return {"url": session.url}


def parse_event(payload: bytes, sig_header: str | None) -> dict:
    """Verify + parse a Stripe webhook. When no webhook secret is configured
    (dev/test), accept the unsigned JSON body."""
    if config.STRIPE_WEBHOOK_SECRET and sig_header:
        stripe = _stripe()
        return stripe.Webhook.construct_event(payload, sig_header, config.STRIPE_WEBHOOK_SECRET)
    try:
        return json.loads(payload)
    except (ValueError, TypeError):
        raise BillingError("invalid webhook payload")


def _workspace_by_subscription(con, sub_id):
    if not sub_id:
        return None
    row = con.execute("SELECT workspace_id FROM subscriptions WHERE stripe_subscription_id = ?", [sub_id]).fetchone()
    return row[0] if row else None


def apply_event(con, event: dict) -> dict:
    """Advance the subscription state machine from a Stripe event."""
    etype = event.get("type")
    obj = (event.get("data") or {}).get("object") or {}

    if etype == "checkout.session.completed":
        ws = obj.get("client_reference_id") or (obj.get("metadata") or {}).get("workspace_id")
        plan = (obj.get("metadata") or {}).get("plan", "pro")
        if ws:
            set_plan(con, ws, plan if plan in ("free", "pro") else "pro", status="active",
                     stripe_customer_id=obj.get("customer"),
                     stripe_subscription_id=obj.get("subscription"))
            return {"handled": etype, "workspace_id": ws}

    elif etype == "customer.subscription.updated":
        ws = _workspace_by_subscription(con, obj.get("id"))
        if ws:
            status = obj.get("status", "active")
            set_plan(con, ws, "pro" if status in ("active", "trialing") else "free", status=status)
            return {"handled": etype, "workspace_id": ws}

    elif etype == "customer.subscription.deleted":
        ws = _workspace_by_subscription(con, obj.get("id"))
        if ws:
            set_plan(con, ws, "free", status="canceled")
            return {"handled": etype, "workspace_id": ws}

    return {"handled": None}
