"""Generate a realistic 24-month company dataset across business units and
branches, with a clear upward trend, mild seasonality, one planted anomaly
(a sharp dip), and a declining branch - so the forecasting, anomaly
detection and auto-insights all have real signal to surface.

Usage: python scripts/make_sample_data.py [--out ../sample_company_sales.csv]
"""

import argparse
import csv
import math
import random
from datetime import date
from pathlib import Path

SEED = 11
MONTHS = [(y, m) for y in (2024, 2025) for m in range(1, 13)]  # 24 months

UNITS = {
    "Retail": ["Delhi", "Mumbai", "Bangalore", "Chennai"],
    "Wholesale": ["Delhi", "Pune", "Hyderabad"],
    "Online": ["Mumbai", "Bangalore"],
}
BASE = {"Retail": 900000, "Wholesale": 1400000, "Online": 550000}
BRANCH_FACTOR = {"Delhi": 1.3, "Mumbai": 1.15, "Bangalore": 1.0,
                 "Chennai": 0.8, "Pune": 0.9, "Hyderabad": 0.85}


def trend(month_idx: int, branch: str) -> float:
    growth = 1.0 + 0.018 * month_idx            # ~1.8% per month company-wide
    if branch == "Chennai":
        growth = max(1.0 - 0.02 * month_idx, 0.4)  # declining branch
    if branch == "Bangalore":
        growth = 1.0 + 0.04 * month_idx            # fast riser
    return growth


def seasonal(month: int) -> float:
    # festive lift around Oct-Dec, dip in Feb
    return 1.0 + 0.10 * math.sin((month - 3) / 12 * 2 * math.pi)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent.parent / "sample_company_sales.csv"))
    args = ap.parse_args()

    rng = random.Random(SEED)
    rows = []
    for i, (year, month) in enumerate(MONTHS):
        d = date(year, month, rng.randint(1, 28))
        for unit, branches in UNITS.items():
            for branch in branches:
                rev = BASE[unit] * BRANCH_FACTOR[branch] * trend(i, branch) * seasonal(month)
                rev *= rng.uniform(0.93, 1.07)
                # planted anomaly: sharp company-wide dip in 2024-08 (idx 7)
                if i == 7:
                    rev *= 0.55
                rev = round(rev, 2)
                units_sold = int(rev / rng.uniform(950, 1150))
                profit = round(rev * rng.uniform(0.12, 0.2), 2)
                customers = int(units_sold * rng.uniform(0.45, 0.65))
                rows.append({
                    "date": d.isoformat(), "business_unit": unit, "branch": branch,
                    "revenue": rev, "units_sold": units_sold,
                    "profit": profit, "customer_count": customers,
                })

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows across 24 months -> {out}")


if __name__ == "__main__":
    main()
