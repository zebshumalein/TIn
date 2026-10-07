"""Built-in sample sales dataset (~300 rows, 12 months, 4 regions, 5 products)."""
from pathlib import Path

import numpy as np
import pandas as pd

SAMPLE_PATH = Path(__file__).with_name("sample_sales.csv")

REGIONS = ["North", "South", "East", "West"]
PRODUCTS = {  # product -> unit price
    "Laptop": 4500,
    "Phone": 2200,
    "Tablet": 1800,
    "Headphones": 350,
    "Monitor": 1200,
}


def build_sample() -> pd.DataFrame:
    rng = np.random.RandomState(42)
    n = 300
    rows = []
    for i in range(n):
        month = i % 12 + 1  # even spread across the 12 months
        day = int(rng.randint(1, 29))
        product = list(PRODUCTS)[int(rng.randint(0, len(PRODUCTS)))]
        region = REGIONS[int(rng.randint(0, len(REGIONS)))]
        units = int(rng.randint(1, 12))
        revenue = int(round(units * PRODUCTS[product] * rng.uniform(0.92, 1.08)))
        rows.append((f"2025-{month:02d}-{day:02d}", region, product, units, revenue))
    df = pd.DataFrame(rows, columns=["date", "region", "product", "units", "revenue"])
    return df.sort_values("date", kind="stable").reset_index(drop=True)


def load_sample() -> pd.DataFrame:
    if not SAMPLE_PATH.exists():
        build_sample().to_csv(SAMPLE_PATH, index=False)
    return pd.read_csv(SAMPLE_PATH)


if __name__ == "__main__":
    build_sample().to_csv(SAMPLE_PATH, index=False)
    print(f"Wrote {SAMPLE_PATH}")
