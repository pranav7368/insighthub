"""Industry templates — a ready-made dataset *plus* the analysis around it.

A template is more than sample rows: it ships the realistic data, the
**certified metrics** that industry actually reports on, and a **default saved
view** that arranges the dashboard to tell that industry's story. One click and
a new user is looking at a dashboard that resembles their own business, with
every number already traceable to SQL.

The generators are pure (no DB, no I/O) and deterministic for a given seed, so
they are cheap to test. The endpoint layer in `main.py` is what turns a
template into a dataset + metrics + view.
"""

import random
from dataclasses import dataclass
from datetime import date
from typing import Callable

import pandas as pd

from .sample import build_sample_df


def _months(n: int) -> list[tuple[int, int]]:
    """The last `n` (year, month) pairs, oldest first, ending with this month."""
    today = date.today()
    out = []
    for i in range(n):
        m = today.month - (n - 1 - i)
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        out.append((y, m))
    return out


# Cities the frontend map can place (see frontend/src/geo.js) — templates that
# use these get a working geo bubble map out of the box.
_METROS = ["Mumbai", "Delhi", "Bangalore", "Hyderabad", "Chennai", "Pune", "Kolkata", "Ahmedabad"]


# ------------------------------------------------------------- builders ----

def build_saas_df(months: int = 12, seed: int = 7) -> pd.DataFrame:
    """Subscription business: MRR by plan and acquisition channel.

    Plan sizes follow the usual pyramid (many Starter, few Enterprise). The
    absolute customer counts matter: with only a handful per segment the churn
    columns collapse to 0/1 and the schema detector reasonably reads them as
    fractions — i.e. renders a headcount as a percentage.
    """
    rng = random.Random(seed)
    # plan -> (monthly price, customers at the base of the pyramid)
    plans = {"Starter": (1200, 420), "Growth": (4800, 180),
             "Scale": (15000, 60), "Enterprise": (42000, 16)}
    channels = {"Organic": 0.40, "Paid": 0.30, "Referral": 0.18, "Partner": 0.12}
    rows = []
    for i, (y, m) in enumerate(_months(months)):
        growth = 1.0 + 0.045 * i                      # compounding-ish MRR growth
        for plan, (price, base) in plans.items():
            for channel, share in channels.items():
                customers = max(2, round(base * share * growth * rng.uniform(0.85, 1.15)))
                mrr = round(customers * price * rng.uniform(0.95, 1.05))
                churned = max(0, round(customers * rng.uniform(0.005, 0.045)))
                rows.append({
                    "date": date(y, m, rng.randint(1, 28)).isoformat(),
                    "plan": plan,
                    "channel": channel,
                    "mrr": mrr,
                    "active_customers": customers,
                    "new_customers": max(1, round(customers * rng.uniform(0.06, 0.18))),
                    "churned_customers": churned,
                    "churned_mrr": round(churned * price),
                    "support_tickets": round(customers * rng.uniform(0.2, 0.9)),
                })
    return pd.DataFrame(rows)


def build_ecommerce_df(months: int = 12, seed: int = 11) -> pd.DataFrame:
    """Online store: orders, returns and discounts by city and category."""
    rng = random.Random(seed)
    categories = {"Electronics": 3400, "Apparel": 1100, "Home": 1800, "Beauty": 700}
    city_weight = {"Mumbai": 1.6, "Delhi": 1.5, "Bangalore": 1.4, "Hyderabad": 1.0,
                   "Chennai": 0.9, "Pune": 0.8, "Kolkata": 0.7, "Ahmedabad": 0.6}
    rows = []
    for i, (y, m) in enumerate(_months(months)):
        season = 1.0 + 0.02 * i + (0.35 if m in (10, 11) else 0.0)   # festive lift
        for city in _METROS:
            for category, aov in categories.items():
                orders = max(5, round(140 * city_weight[city] * season * rng.uniform(0.8, 1.2)))
                revenue = round(orders * aov * rng.uniform(0.85, 1.15))
                rows.append({
                    "date": date(y, m, rng.randint(1, 28)).isoformat(),
                    "city": city,
                    "category": category,
                    "channel": rng.choice(["App", "Web", "Marketplace"]),
                    "orders": orders,
                    "revenue": revenue,
                    "discount": round(revenue * rng.uniform(0.04, 0.22)),
                    "returns": max(0, round(orders * rng.uniform(0.01, 0.09))),
                    "delivery_days": round(rng.uniform(1.5, 5.5), 1),
                })
    return pd.DataFrame(rows)


def build_logistics_df(months: int = 12, seed: int = 13) -> pd.DataFrame:
    """Freight operations: shipments, on-time delivery and cost by hub."""
    rng = random.Random(seed)
    hubs = {"Mumbai": 1.5, "Delhi": 1.4, "Bangalore": 1.1, "Chennai": 0.9,
            "Kolkata": 0.8, "Ahmedabad": 0.7}
    carriers = {"BlueDart": 0.96, "Delhivery": 0.93, "In-house Fleet": 0.88}
    rows = []
    for i, (y, m) in enumerate(_months(months)):
        volume = 1.0 + 0.025 * i
        monsoon = 0.94 if m in (7, 8) else 1.0                       # seasonal dip
        for hub, weight in hubs.items():
            for carrier, base_otd in carriers.items():
                shipments = max(20, round(900 * weight * volume * rng.uniform(0.85, 1.15)))
                otd = min(0.995, max(0.6, base_otd * monsoon * rng.uniform(0.97, 1.03)))
                rows.append({
                    "date": date(y, m, rng.randint(1, 28)).isoformat(),
                    "hub": hub,
                    "carrier": carrier,
                    "shipments": shipments,
                    "delivered_on_time": round(shipments * otd),
                    "freight_cost": round(shipments * rng.uniform(180, 340)),
                    "delay_hours": round(rng.uniform(1.0, 14.0) * (2.0 - otd), 1),
                })
    return pd.DataFrame(rows)


def build_healthcare_df(months: int = 12, seed: int = 17) -> pd.DataFrame:
    """Multi-speciality clinic: visits, wait time and cost by department."""
    rng = random.Random(seed)
    departments = {"General Medicine": 1.6, "Orthopaedics": 0.9, "Paediatrics": 1.1,
                   "Cardiology": 0.7, "Dermatology": 0.8, "Diagnostics": 1.3}
    visit_types = {"Walk-in": (900, 1.4), "Appointment": (1600, 1.0), "Follow-up": (600, 0.8)}
    rows = []
    for i, (y, m) in enumerate(_months(months)):
        load = 1.0 + 0.015 * i + (0.2 if m in (12, 1, 2) else 0.0)   # winter OPD load
        for dept, dept_w in departments.items():
            for visit_type, (fee, type_w) in visit_types.items():
                visits = max(10, round(260 * dept_w * type_w * load * rng.uniform(0.85, 1.15)))
                revenue = round(visits * fee * rng.uniform(0.9, 1.1))
                rows.append({
                    "date": date(y, m, rng.randint(1, 28)).isoformat(),
                    "department": dept,
                    "visit_type": visit_type,
                    "visits": visits,
                    "revenue": revenue,
                    "cost": round(revenue * rng.uniform(0.55, 0.8)),
                    "wait_minutes": round(rng.uniform(8, 55) * type_w, 1),
                    "no_shows": max(0, round(visits * rng.uniform(0.02, 0.12))),
                })
    return pd.DataFrame(rows)


# ------------------------------------------------------------- registry ----

def _agg(agg: str, column: str | None = None) -> dict:
    return {"agg": agg} if column is None else {"agg": agg, "column": column}


def _ratio(num: dict, den: dict) -> dict:
    return {"numerator": num, "denominator": den}


@dataclass(frozen=True)
class Metric:
    """A certified metric a template ships with (see analytics/semantic.py)."""
    name: str
    kind: str            # "aggregate" | "ratio"
    definition: dict
    format: str | None = None


@dataclass(frozen=True)
class Template:
    id: str
    label: str           # short name shown on the template card
    industry: str
    icon: str            # single emoji for the card
    description: str
    dataset_name: str
    highlights: tuple[str, ...]
    build: Callable[[], pd.DataFrame]
    metrics: tuple[Metric, ...] = ()
    view_name: str = "Overview"
    # the headline measure the dashboard should follow. Pinning it explicitly
    # both picks the right story and keeps the saved view clean — a view with no
    # measure is reported "unsaved" the moment the engine auto-chooses one.
    measure: str = ""
    # sections hidden by default in the template's saved view
    hidden_sections: tuple[str, ...] = ()
    # leading section order; any section not listed keeps its natural position
    section_order: tuple[str, ...] = ()

    def view_config(self) -> dict:
        return {
            "filters": {},
            "date_from": None,
            "date_to": None,
            "measure": self.measure or None,
            "hidden_sections": list(self.hidden_sections),
            "section_order": list(self.section_order),
        }

    def as_card(self) -> dict:
        """The catalog shape the frontend renders (no builders/definitions)."""
        return {
            "id": self.id, "label": self.label, "industry": self.industry,
            "icon": self.icon, "description": self.description,
            "dataset_name": self.dataset_name, "highlights": list(self.highlights),
            "metrics": [m.name for m in self.metrics],
        }


TEMPLATES: tuple[Template, ...] = (
    Template(
        id="retail",
        label="Retail Sales",
        industry="Retail",
        icon="🛍️",
        description="Monthly revenue, profit and units across regions and products.",
        dataset_name="Sample — Retail Sales",
        highlights=("Revenue trend & forecast", "Region / product mix", "80-20 Pareto"),
        build=build_sample_df,
        metrics=(
            Metric("Revenue", "aggregate", _agg("sum", "revenue"), "currency"),
            Metric("Gross Profit", "aggregate", _agg("sum", "profit"), "currency"),
            Metric("Gross Margin", "ratio", _ratio(_agg("sum", "profit"), _agg("sum", "revenue")), "percent"),
            Metric("Revenue per Unit", "ratio", _ratio(_agg("sum", "revenue"), _agg("sum", "units_sold")), "currency"),
        ),
        measure="revenue",
        hidden_sections=("map",),
        section_order=("kpis", "metrics", "growth", "forecast", "breakdowns", "pareto", "insights"),
    ),
    Template(
        id="saas",
        label="SaaS Subscriptions",
        industry="SaaS / Software",
        icon="📈",
        description="MRR, churn and ARPU by plan tier and acquisition channel.",
        dataset_name="Sample — SaaS Subscriptions",
        highlights=("MRR growth & forecast", "Churn by plan", "ARPU per channel"),
        build=build_saas_df,
        metrics=(
            Metric("MRR", "aggregate", _agg("sum", "mrr"), "currency"),
            Metric("Customer Churn Rate", "ratio",
                   _ratio(_agg("sum", "churned_customers"), _agg("sum", "active_customers")), "percent"),
            Metric("Revenue Churn Rate", "ratio",
                   _ratio(_agg("sum", "churned_mrr"), _agg("sum", "mrr")), "percent"),
            Metric("ARPU", "ratio", _ratio(_agg("sum", "mrr"), _agg("sum", "active_customers")), "currency"),
        ),
        measure="mrr",
        hidden_sections=("map", "treemap"),
        section_order=("kpis", "metrics", "growth", "forecast", "drivers", "breakdowns", "correlations"),
    ),
    Template(
        id="ecommerce",
        label="E-commerce Orders",
        industry="E-commerce",
        icon="🛒",
        description="Orders, returns and discounting by city, category and channel.",
        dataset_name="Sample — E-commerce Orders",
        highlights=("City map of demand", "Return & discount rates", "Festive season lift"),
        build=build_ecommerce_df,
        metrics=(
            Metric("Revenue", "aggregate", _agg("sum", "revenue"), "currency"),
            Metric("Average Order Value", "ratio",
                   _ratio(_agg("sum", "revenue"), _agg("sum", "orders")), "currency"),
            Metric("Return Rate", "ratio", _ratio(_agg("sum", "returns"), _agg("sum", "orders")), "percent"),
            Metric("Discount Rate", "ratio", _ratio(_agg("sum", "discount"), _agg("sum", "revenue")), "percent"),
        ),
        measure="revenue",
        section_order=("kpis", "metrics", "map", "growth", "forecast", "breakdowns", "pareto"),
    ),
    Template(
        id="logistics",
        label="Logistics & Delivery",
        industry="Logistics",
        icon="🚚",
        description="Shipment volume, on-time delivery and freight cost per hub.",
        dataset_name="Sample — Logistics & Delivery",
        highlights=("On-time % by carrier", "Hub map", "Cost per shipment"),
        build=build_logistics_df,
        metrics=(
            Metric("Shipments", "aggregate", _agg("sum", "shipments"), "number"),
            Metric("On-time Delivery", "ratio",
                   _ratio(_agg("sum", "delivered_on_time"), _agg("sum", "shipments")), "percent"),
            Metric("Cost per Shipment", "ratio",
                   _ratio(_agg("sum", "freight_cost"), _agg("sum", "shipments")), "currency"),
            Metric("Average Delay", "aggregate", _agg("avg", "delay_hours"), "number"),
        ),
        measure="shipments",
        hidden_sections=("treemap",),
        section_order=("kpis", "metrics", "map", "drivers", "breakdowns", "forecast", "correlations"),
    ),
    Template(
        id="healthcare",
        label="Clinic Operations",
        industry="Healthcare",
        icon="🩺",
        description="Patient visits, wait times and cost ratio across departments.",
        dataset_name="Sample — Clinic Operations",
        highlights=("Visits by department", "Wait time outliers", "No-show rate"),
        build=build_healthcare_df,
        metrics=(
            Metric("Patient Visits", "aggregate", _agg("sum", "visits"), "number"),
            Metric("Revenue", "aggregate", _agg("sum", "revenue"), "currency"),
            Metric("Cost Ratio", "ratio", _ratio(_agg("sum", "cost"), _agg("sum", "revenue")), "percent"),
            Metric("No-show Rate", "ratio", _ratio(_agg("sum", "no_shows"), _agg("sum", "visits")), "percent"),
            Metric("Average Wait", "aggregate", _agg("avg", "wait_minutes"), "number"),
        ),
        measure="visits",
        hidden_sections=("map", "treemap"),
        section_order=("kpis", "metrics", "insights", "drivers", "breakdowns", "distributions", "forecast"),
    ),
)

_BY_ID = {t.id: t for t in TEMPLATES}
DEFAULT_TEMPLATE_ID = "retail"


class UnknownTemplate(ValueError):
    """No template with that id."""


def get_template(template_id: str) -> Template:
    tpl = _BY_ID.get((template_id or "").strip().lower())
    if tpl is None:
        raise UnknownTemplate(f"unknown template {template_id!r}")
    return tpl


def catalog() -> list[dict]:
    return [t.as_card() for t in TEMPLATES]
