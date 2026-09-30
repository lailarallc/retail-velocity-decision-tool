"""Reload Postgres tables from the SQLite source database.

DISABLED: Platform ingest is now owned by Dagster/dbt. This legacy loader
DROP/CREATEs canonical tables (dim_products, stg_sku_costs, fct_distribution,
stg_stores, stg_scan_data, stg_promotions, stg_price_history) and would
overwrite the pipeline's authoritative data if run. Kept for reference only.

Requires: fly proxy 15432:5432 --app cinderhaven-db running in background.
Production runs now need ALLOW_PROD_DB=1 (prod_guard refuses a fly tunnel otherwise).

Usage:
    set DATABASE_URL=postgres://user:pass@localhost:15432/cinderhaven
    set SQLITE_PATH=C:\\path\\to\\cinderhaven_product_master.db
    python reload_postgres.py
"""
from __future__ import annotations

import sys

def _guard() -> None:
    print(
        "DISABLED — platform ingest is owned by Dagster/dbt.\n"
        "This legacy loader DROP/CREATEs canonical tables and would overwrite\n"
        "authoritative pipeline data. Do not bypass this guard.\n"
        "\n"
        "Tables affected: dim_products, stg_sku_costs, fct_distribution,\n"
        "stg_stores, stg_scan_data, stg_promotions, stg_price_history,\n"
        "stg_category_benchmarks.\n"
        "\n"
        "If you need to reload data, use the Dagster/dbt pipeline."
    )
    sys.exit(1)

_guard()

import csv
import io
import os
import sqlite3
import sys
from typing import Any

import psycopg2
import psycopg2.extensions

import prod_guard

SQLITE_PATH = os.environ.get("SQLITE_PATH", "")
PG_DSN = os.environ.get("DATABASE_URL", "postgres://localhost:15432/cinderhaven")

# Retailer name normalization: source data -> app constants
RETAILER_NAME_MAP = {
    "Regional Group": "Regional",
}

CATEGORY_MAP = {
    "Artisan Sauces": "Sauces & Marinades",
    "Specialty Condiments": "Condiments & Dressings",
    "Pantry Staples": "Dry Grocery & Baking",
}

# Benchmark multipliers: Cinderhaven's own velocity scaled to approximate
# a category-level average. These are synthetic proxies, not external data.
# > 1.0 means the category average is higher (Cinderhaven underperforms).
BENCHMARK_MULTIPLIERS = {
    "Sauces & Marinades": 0.92,
    "Condiments & Dressings": 1.22,
    "Dry Grocery & Baking": 1.35,
}

RETAILER_ADJUSTMENTS = {
    "Walmart": 1.0,
    "Costco": 0.85,
    "Whole Foods": 1.10,
    "Kroger": 1.0,
    "Sprouts": 1.08,
}

_VALID_TABLES = frozenset({
    "stg_stores", "stg_scan_data", "dim_products", "stg_sku_costs",
    "stg_promotions", "stg_price_history", "fct_distribution",
})

TABLE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "stg_stores": {
        "source": "stores",
        "create": """
            CREATE TABLE stg_stores (
                store_id TEXT PRIMARY KEY,
                retailer TEXT NOT NULL,
                chain_name TEXT,
                region TEXT,
                state TEXT,
                volume_tier TEXT,
                is_aggregated_channel BOOLEAN NOT NULL DEFAULT false
            )
        """,
        "columns": ["store_id", "retailer", "chain_name", "region", "state", "volume_tier", "is_aggregated_channel"],
        "transforms": {"is_aggregated_channel": lambda v: v == 1},
    },
    "stg_scan_data": {
        "source": "scan_data",
        "create": """
            CREATE TABLE stg_scan_data (
                sku TEXT NOT NULL,
                store_id TEXT NOT NULL,
                week_ending DATE NOT NULL,
                units_sold INTEGER NOT NULL,
                dollars_sold REAL
            )
        """,
        "columns": ["sku", "store_id", "week_ending", "units_sold", "dollars_sold"],
        "transforms": {},
    },
    "dim_products": {
        "source": "product_master",
        "create": """
            CREATE TABLE dim_products (
                sku TEXT PRIMARY KEY,
                product_name TEXT NOT NULL,
                product_line TEXT NOT NULL,
                subcategory TEXT,
                gtin14 TEXT,
                upc TEXT,
                case_pack_qty INTEGER,
                unit_weight_lbs REAL,
                case_weight_lbs REAL,
                case_length_in REAL,
                case_width_in REAL,
                case_height_in REAL,
                msrp REAL,
                serving_size TEXT,
                calories_per_serving REAL,
                total_fat_g REAL,
                sodium_mg INTEGER,
                total_carb_g REAL,
                protein_g REAL,
                brand_owner TEXT,
                country_of_origin TEXT,
                active_retailers TEXT,
                oneworldsync_status TEXT,
                last_updated TEXT,
                updated_by TEXT,
                category TEXT
            )
        """,
        "columns": ["sku", "product_name", "product_line", "subcategory", "gtin14", "upc",
                     "case_pack_qty", "unit_weight_lbs", "case_weight_lbs", "case_length_in",
                     "case_width_in", "case_height_in", "msrp", "serving_size",
                     "calories_per_serving", "total_fat_g", "sodium_mg", "total_carb_g",
                     "protein_g", "brand_owner", "country_of_origin", "active_retailers",
                     "oneworldsync_status", "last_updated", "updated_by"],
        "transforms": {},
    },
    "stg_sku_costs": {
        "source": "sku_costs",
        "create": """
            CREATE TABLE stg_sku_costs (
                sku TEXT PRIMARY KEY,
                cogs_per_unit REAL,
                landed_cost_per_unit REAL,
                wholesale_price REAL,
                wholesale_walmart REAL,
                wholesale_costco REAL,
                wholesale_whole_foods REAL,
                wholesale_regional REAL,
                wholesale_unfi REAL,
                wholesale_kehe REAL,
                wholesale_dtc REAL,
                trade_spend_pct_walmart REAL,
                trade_spend_pct_costco REAL,
                trade_spend_pct_whole_foods REAL,
                trade_spend_pct_regional REAL,
                trade_spend_pct_unfi REAL,
                trade_spend_pct_kehe REAL,
                trade_spend_pct_dtc REAL
            )
        """,
        "columns": ["sku", "cogs_per_unit", "landed_cost_per_unit", "wholesale_price",
                     "wholesale_walmart", "wholesale_costco", "wholesale_whole_foods",
                     "wholesale_regional", "wholesale_unfi", "wholesale_kehe", "wholesale_dtc",
                     "trade_spend_pct_walmart", "trade_spend_pct_costco",
                     "trade_spend_pct_whole_foods", "trade_spend_pct_regional",
                     "trade_spend_pct_unfi", "trade_spend_pct_kehe", "trade_spend_pct_dtc"],
        "transforms": {},
    },
    "stg_promotions": {
        "source": "promotions",
        "create": """
            CREATE TABLE stg_promotions (
                promo_id TEXT,
                sku TEXT NOT NULL,
                retailer TEXT NOT NULL,
                store_scope TEXT,
                start_week DATE,
                end_week DATE,
                duration_weeks INTEGER,
                discount_depth_pct REAL,
                promo_type TEXT,
                promo_cost REAL,
                funding_mechanism TEXT
            )
        """,
        "columns": ["promo_id", "sku", "retailer", "store_scope", "start_week", "end_week",
                     "duration_weeks", "discount_depth_pct", "promo_type", "promo_cost",
                     "funding_mechanism"],
        "transforms": {},
    },
    "stg_price_history": {
        "source": "price_history",
        "create": """
            CREATE TABLE stg_price_history (
                sku TEXT NOT NULL,
                retailer TEXT NOT NULL,
                effective_date DATE,
                wholesale_price REAL
            )
        """,
        "columns": ["sku", "retailer", "effective_date", "wholesale_price"],
        "transforms": {},
    },
    "fct_distribution": {
        "source": "distribution_log",
        "create": """
            CREATE TABLE fct_distribution (
                sku TEXT NOT NULL,
                store_id TEXT NOT NULL,
                authorized_date DATE,
                deauthorized_date DATE
            )
        """,
        "columns": ["sku", "store_id", "authorized_date", "deauthorized_date"],
        "transforms": {},
    },
}


def _serialize_value(v: object) -> str:
    """Serialize a Python value for Postgres COPY TSV format."""
    if v is None:
        return ''
    if v is True:
        return 'true'
    if v is False:
        return 'false'
    return str(v)


def load_table(
    sqlite_conn: sqlite3.Connection,
    pg_cur: psycopg2.extensions.cursor,
    table_name: str,
    table_def: dict[str, Any],
) -> None:
    assert table_name in _VALID_TABLES, f"Unknown table: {table_name}"
    source = table_def["source"]
    columns = table_def["columns"]
    transforms = table_def.get("transforms", {})

    print(f"\n--- {table_name} (from {source}) ---")

    rows = sqlite_conn.execute(f"SELECT {', '.join(columns)} FROM [{source}]").fetchall()
    print(f"  Read {len(rows)} rows from SQLite")

    if not rows:
        print("  (empty table, skipping)")
        return

    pg_cur.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
    pg_cur.execute(f"DROP VIEW IF EXISTS {table_name} CASCADE")
    pg_cur.execute(table_def["create"])

    if transforms:
        transformed = []
        for row in rows:
            new_row = list(row)
            for col_name, fn in transforms.items():
                idx = columns.index(col_name)
                new_row[idx] = fn(row[idx])
            transformed.append(new_row)
        rows = transformed

    buf = io.StringIO()
    writer = csv.writer(buf, delimiter='\t', lineterminator='\n')
    for row in rows:
        writer.writerow([_serialize_value(v) for v in row])
    buf.seek(0)

    pg_cur.copy_from(buf, table_name, columns=columns, null='')
    print(f"  Loaded {len(rows)} rows into Postgres")

    pg_cur.execute(f"SELECT COUNT(*) FROM {table_name}")
    print(f"  Verified: {pg_cur.fetchone()[0]} rows")


def normalize_retailers(pg_cur: psycopg2.extensions.cursor) -> None:
    """Rename retailer values in stg_stores to match app constants."""
    print("\n--- Normalizing retailer names ---")
    for source_name, target_name in RETAILER_NAME_MAP.items():
        pg_cur.execute(
            "UPDATE stg_stores SET retailer = %s WHERE retailer = %s",
            (target_name, source_name),
        )
        if pg_cur.rowcount:
            print(f"  {source_name} -> {target_name} ({pg_cur.rowcount} rows)")


def add_category_column(pg_cur: psycopg2.extensions.cursor) -> None:
    print("\n--- Adding category column to dim_products ---")
    for product_line, category in CATEGORY_MAP.items():
        pg_cur.execute(
            "UPDATE dim_products SET category = %s WHERE product_line = %s",
            (category, product_line),
        )
        print(f"  {product_line} -> {category}")

    pg_cur.execute("SELECT COUNT(*) FROM dim_products WHERE category IS NOT NULL")
    print(f"  {pg_cur.fetchone()[0]} products categorized")


def seed_benchmarks(pg_cur: psycopg2.extensions.cursor) -> None:
    """Seed synthetic category benchmarks from Cinderhaven's own scan data.

    Multiplies Cinderhaven's average velocity by fixed factors to approximate
    what a category management platform would report as the category average.
    """
    print("\n--- Seeding stg_category_benchmarks ---")
    pg_cur.execute("""
        CREATE TABLE IF NOT EXISTS stg_category_benchmarks (
            category     TEXT    NOT NULL,
            retailer     TEXT    NOT NULL,
            week_ending  DATE    NOT NULL,
            avg_velocity NUMERIC(10, 4) NOT NULL,
            PRIMARY KEY (category, retailer, week_ending)
        )
    """)

    pg_cur.execute("""
        SELECT DISTINCT s.retailer
        FROM stg_stores s
        WHERE s.is_aggregated_channel = false
          AND s.retailer NOT IN ('UNFI', 'KeHE', 'DTC')
    """)
    retailers = [r[0] for r in pg_cur.fetchall()]
    print(f"  Retailers: {retailers}")

    total = 0
    for category, mult in BENCHMARK_MULTIPLIERS.items():
        for retailer in retailers:
            ret_adj = RETAILER_ADJUSTMENTS.get(retailer, 1.05)
            final_mult = mult * ret_adj

            pg_cur.execute("""
                INSERT INTO stg_category_benchmarks
                    (category, retailer, week_ending, avg_velocity)
                SELECT
                    %s AS category,
                    %s AS retailer,
                    d.week_ending,
                    AVG(d.units_sold) * %s AS avg_velocity
                FROM stg_scan_data d
                JOIN stg_stores s ON d.store_id = s.store_id
                JOIN dim_products pm ON d.sku = pm.sku
                WHERE pm.category = %s
                  AND s.retailer = %s
                  AND s.is_aggregated_channel = false
                GROUP BY d.week_ending
                ON CONFLICT (category, retailer, week_ending)
                DO UPDATE SET avg_velocity = EXCLUDED.avg_velocity
            """, (category, retailer, final_mult, category, retailer))
            rows = pg_cur.rowcount
            total += rows
            print(f"  {category} x {retailer}: {rows} weeks")

    print(f"  Total: {total} benchmark rows")


def create_indexes(pg_cur: psycopg2.extensions.cursor) -> None:
    print("\n--- Creating indexes ---")
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_scan_data_store ON stg_scan_data(store_id)",
        "CREATE INDEX IF NOT EXISTS idx_scan_data_sku ON stg_scan_data(sku)",
        "CREATE INDEX IF NOT EXISTS idx_scan_data_week ON stg_scan_data(week_ending)",
        "CREATE INDEX IF NOT EXISTS idx_scan_data_sku_store ON stg_scan_data(sku, store_id)",
        "CREATE INDEX IF NOT EXISTS idx_stores_retailer ON stg_stores(retailer)",
        "CREATE INDEX IF NOT EXISTS idx_fct_dist_sku ON fct_distribution(sku)",
        "CREATE INDEX IF NOT EXISTS idx_fct_dist_store ON fct_distribution(store_id)",
        "CREATE INDEX IF NOT EXISTS idx_promos_sku ON stg_promotions(sku)",
        "CREATE INDEX IF NOT EXISTS idx_benchmarks_cat_ret ON stg_category_benchmarks(category, retailer)",
    ]
    for idx in indexes:
        name = idx.split("idx_")[1].split(" ")[0]
        pg_cur.execute(idx)
        print(f"  Created idx_{name}")


def main() -> None:
    if not SQLITE_PATH:
        print("ERROR: SQLITE_PATH not set. Export it or pass as env var.")
        print("  e.g.: set SQLITE_PATH=C:\\path\\to\\cinderhaven_product_master.db")
        sys.exit(1)
    if not os.path.exists(SQLITE_PATH):
        print(f"ERROR: SQLite file not found: {SQLITE_PATH}")
        sys.exit(1)

    print(f"Connecting to SQLite ({SQLITE_PATH})...")
    with sqlite3.connect(SQLITE_PATH) as sqlite_conn:
        print("Connecting to Postgres (via fly proxy)...")
        prod_guard.check(PG_DSN)  # refuses a fly tunnel to production
        try:
            pg_conn = psycopg2.connect(PG_DSN, connect_timeout=5)
        except psycopg2.Error as e:
            print(f"ERROR: Cannot connect to Postgres: {type(e).__name__}")
            print("Make sure 'fly proxy 15432:5432 --app cinderhaven-db' is running.")
            sys.exit(1)

        try:
            pg_conn.autocommit = False
            with pg_conn.cursor() as cur:
                failed: list[str] = []
                for table_name, table_def in TABLE_DEFINITIONS.items():
                    try:
                        load_table(sqlite_conn, cur, table_name, table_def)
                    except Exception as e:
                        print(f"  ERROR loading {table_name}: {e}")
                        failed.append(table_name)
                        pg_conn.rollback()

                if failed:
                    print(f"\nFailed tables: {failed}")
                    print("Rolling back all changes.")
                    pg_conn.rollback()
                    sys.exit(1)

                normalize_retailers(cur)
                add_category_column(cur)
                seed_benchmarks(cur)
                create_indexes(cur)

                pg_conn.commit()
                print("\n=== All tables loaded and committed successfully ===")
        finally:
            pg_conn.close()


if __name__ == "__main__":
    main()
