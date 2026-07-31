"""Built-in sample dataset — one click so a brand-new user immediately sees a
full, realistic dashboard (trend, regions, products, margin, drivers)."""

import random
from datetime import date

import pandas as pd

REGIONS = ["North", "South", "East", "West"]
PRODUCTS = ["Widget", "Gadget", "Gizmo"]
_REGION_WEIGHT = {"North": 1.5, "South": 1.0, "East": 0.8, "West": 1.1}
_PRODUCT_WEIGHT = {"Widget": 1.3, "Gadget": 1.0, "Gizmo": 0.7}


def build_sample_df(months: int = 12, seed: int = 42) -> pd.DataFrame:
    rng = random.Random(seed)
    today = date.today()
    # first day of the month that is (months-1) back, iterate forward
    base_year = today.year
    base_month = today.month
    rows = []
    for i in range(months):
        # month index counting back from current
        m = base_month - (months - 1 - i)
        y = base_year
        while m <= 0:
            m += 12
            y -= 1
        trend = 1.0 + 0.03 * i  # gentle upward trend over time
        for region in REGIONS:
            for product in PRODUCTS:
                day = rng.randint(1, 28)
                base = 8000 * _REGION_WEIGHT[region] * _PRODUCT_WEIGHT[product] * trend
                revenue = round(base * rng.uniform(0.85, 1.15))
                margin = rng.uniform(0.18, 0.32)
                profit = round(revenue * margin)
                units = round(revenue / rng.uniform(90, 130))
                rows.append({
                    "date": date(y, m, day).isoformat(),
                    "region": region,
                    "product": product,
                    "revenue": revenue,
                    "profit": profit,
                    "units_sold": units,
                })
    return pd.DataFrame(rows)
