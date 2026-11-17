"""Seed category benchmarking data into the Cinderhaven database.

One-time script. Run with:  python seed_benchmarks.py

Creates, in this repo's own schema retail_velocity_decision_tool (U19a: no
consumer writes a platform schema):
  - stg_category_benchmarks table with synthetic category-level velocity
    averages per retailer × week

It reads the platform's marts and writes nothing there: each product line's
market category comes from constants.CATEGORY_MAP, joined in the query, not
from a column added to public_marts.dim_products. In production the schema is
created by the platform's owner-run scripts/move_writer_tables.ps1.

The benchmark data simulates what a category management platform would
provide: the average velocity across ALL brands in a market category,
not just Cinderhaven. This gives the tool the "how do I compare?" context
that every paid retail analytics platform charges for.
"""

from __future__ import annotations

import os
import sys

import psycopg2

import prod_guard
from constants import CATEGORY_MAP

SCHEMA = "retail_velocity_decision_tool"
TABLE = f"{SCHEMA}.stg_category_benchmarks"
# Benchmark multipliers: category average velocity relative to Cinderhaven.
# > 1.0 means the category average is higher (Cinderhaven underperforms).
# < 1.0 means Cinderhaven outperforms the category.
#
# Most mid-size brands sit below category averages because category leaders
# (Heinz, Hellmann's, etc.) pull the mean up. One category where Cinderhaven
# excels — Sauces — reflects its artisan positioning in a premium niche.

BENCHMARK_MULTIPLIERS = {
    "Sauces & Marinades":       0.92,   # Cinderhaven outperforms (niche leader)
    "Condiments & Dressings":   1.22,   # below category avg (crowded shelf)
    "Dry Grocery & Baking":     1.35,   # well below (dominated by large brands)
}

# Per-retailer adjustment: category dynamics differ by retailer.
RETAILER_ADJUSTMENTS = {
    "Walmart":     1.0,     # baseline
    "Costco":      0.85,    # club-pack velocity higher; narrows the gap
    "Whole Foods": 1.10,    # premium channel; bigger brands have less edge
    "Kroger":      1.0,     # conventional grocery, similar to Walmart
    "Sprouts":     1.08,    # specialty natural, similar to Whole Foods
}


def main() -> None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL not set. Export it or add to .env.")
        sys.exit(1)

    prod_guard.check(url)  # refuses a fly tunnel to production
    conn = psycopg2.connect(url, options="-c search_path=public_marts,public_staging,raw,public")
    try:
        conn.autocommit = True
        cur = conn.cursor()

        # ----------------------------------------------------------
        # Step 1: Product line → market category, from CATEGORY_MAP
        # (read in the query below; the platform's dim_products is not altered)
        # ----------------------------------------------------------
        lines_by_category: dict[str, list[str]] = {}
        for product_line, category in CATEGORY_MAP.items():
            lines_by_category.setdefault(category, []).append(product_line)
            print(f"  {product_line} → {category}")

        # ----------------------------------------------------------
        # Step 2: Create the benchmarks table in this repo's schema
        # ----------------------------------------------------------
        cur.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (SCHEMA,))
        if cur.fetchone() is None:
            # Only a missing schema is made here: Postgres tests the
            # database privilege before IF NOT EXISTS.
            cur.execute(f"CREATE SCHEMA {SCHEMA}")
        print(f"\nCreating {TABLE} table...")
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE} (
                category     TEXT    NOT NULL,
                retailer     TEXT    NOT NULL,
                week_ending  DATE    NOT NULL,
                avg_velocity NUMERIC(10, 4) NOT NULL,
                PRIMARY KEY (category, retailer, week_ending)
            )
        """)
        cur.execute(f"DELETE FROM {TABLE}")

        # ----------------------------------------------------------
        # Step 3: Compute Cinderhaven's velocity and scale to category
        # ----------------------------------------------------------
        print("Computing category benchmarks from Cinderhaven velocity data...")

        cur.execute("""
            SELECT DISTINCT s.retailer
            FROM dim_stores s
        """)
        retailers = [r[0] for r in cur.fetchall()]

        total_rows = 0
        for category, mult in BENCHMARK_MULTIPLIERS.items():
            for retailer in retailers:
                ret_adj = RETAILER_ADJUSTMENTS.get(retailer, 1.05)
                final_mult = mult * ret_adj

                cur.execute(f"""
                    INSERT INTO {TABLE}
                        (category, retailer, week_ending, avg_velocity)
                    SELECT
                        %s AS category,
                        %s AS retailer,
                        d.week_ending,
                        AVG(d.units_sold) * %s AS avg_velocity
                    FROM fct_scan_data d
                    JOIN dim_stores s ON d.store_id = s.store_id
                    JOIN dim_products pm ON d.sku = pm.sku
                    WHERE pm.product_line = ANY(%s)
                      AND s.retailer = %s
                    GROUP BY d.week_ending
                    ON CONFLICT (category, retailer, week_ending)
                    DO UPDATE SET avg_velocity = EXCLUDED.avg_velocity
                """, (category, retailer, final_mult, lines_by_category.get(category, []), retailer))
                rows = cur.rowcount
                total_rows += rows
                print(f"  {category} × {retailer}: {rows} weeks")

        print(f"\nDone. Inserted {total_rows} benchmark rows.")

        # ----------------------------------------------------------
        # Verify
        # ----------------------------------------------------------
        cur.execute(f"SELECT COUNT(*) FROM {TABLE}")
        print(f"Verification: {cur.fetchone()[0]} rows in {TABLE}")

        cur.execute(f"""
            SELECT category, retailer, ROUND(AVG(avg_velocity), 2) AS avg_v
            FROM {TABLE}
            GROUP BY category, retailer
            ORDER BY category, retailer
        """)
        print("\nCategory × Retailer averages:")
        for row in cur.fetchall():
            print(f"  {row[0]:30s}  {row[1]:15s}  {row[2]} units/store/wk")

        cur.close()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
