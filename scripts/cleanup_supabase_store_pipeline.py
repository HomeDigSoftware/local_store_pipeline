# NEW — safe one-time cleanup of non-read-set tables in Supabase `store_pipeline`. DRY-RUN by default.
"""
cleanup_supabase_store_pipeline.py — drop the prod tables the dashboard never reads.

Companion to 05_publish_dashboard_models.py. Once prod is loaded by the DML
publisher (the ~20-object read-set), the other ~25 tables that the old
`dbt run --target prod` left behind (all staging, fct_sales, most intermediates,
dim_date, the 43 MB fct_inventory_snapshot_history, snapshots, …) are dead weight:
they still occupy storage AND are re-introspected by PostgREST on every schema
reload. This drops everything in `store_pipeline` EXCEPT the read-set.

SAFETY
------
* DRY-RUN by default — prints what WOULD be dropped and changes nothing.
* `--apply` actually drops, and ONLY after you type the exact confirmation string.
* Touches ONLY schema `store_pipeline`. Never touches `raw`.
* Never drops a table in KEEP (the dashboard read-set).

⚠️ GATE — do these FIRST, or the dashboard will break:
   1. Website agent CONFIRMS the read-set (DASHBOARD_PROD_TABLE_ALLOWLIST_2026-06-28.md)
      — esp. that nothing is read dynamically / via API routes / cron.
   2. 05_publish_dashboard_models.py --apply has run (the read-set is freshly loaded).
   3. Then run this cleanup.

Usage:
   uv run python scripts/cleanup_supabase_store_pipeline.py            # dry-run (safe)
   uv run python scripts/cleanup_supabase_store_pipeline.py --apply    # drops, with confirmation
"""

import os
import argparse
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import sqlalchemy as sa
from sqlalchemy import text

SUPABASE_URL = os.environ["SUPABASE_URL"]
TARGET_SCHEMA = "store_pipeline"

# The dashboard read-set. Must match ALLOWLIST in 05_publish_dashboard_models.py.
KEEP = {
    "rpt_category_performance_30d",
    "rpt_daily_sales",
    "rpt_employee_productivity",
    "rpt_executive_summary_daily",
    "rpt_inventory_actions",
    "rpt_inventory_health_trend",
    "rpt_inventory_risk",
    "rpt_payment_mix_daily",
    "rpt_product_performance_30d",
    "rpt_product_velocity",
    "rpt_returns_analysis_daily",
    "rpt_sales_by_hour",
    "rpt_sales_trend_daily",
    "rpt_workforce_productivity_summary",
    "dim_product",
    "int_sales__daily_product",
    "fct_employee_shift",
    "rpt_item_stockout_days",
    "rpt_sales_by_hour_weekday",
    "rpt_staffing_vs_sales_by_hour",
}


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Drop non-read-set tables from Supabase store_pipeline (dry-run by default).")
    ap.add_argument("--apply", action="store_true", help="actually DROP (default: dry-run only)")
    args = ap.parse_args()

    engine = sa.create_engine(SUPABASE_URL)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "select table_name from information_schema.tables "
                "where table_schema = :s and table_type = 'BASE TABLE' order by 1"
            ),
            {"s": TARGET_SCHEMA},
        ).fetchall()
    all_tables = [r[0] for r in rows]
    to_drop = [t for t in all_tables if t not in KEEP]
    missing_keep = sorted(t for t in KEEP if t not in all_tables)

    print(f"\nSchema '{TARGET_SCHEMA}':  {len(all_tables)} tables total")
    print(f"KEEP (read-set) :  {len(KEEP)}")
    print(f"DROP candidates :  {len(to_drop)}")
    for t in to_drop:
        print("   -", t)
    if missing_keep:
        print(f"\n⚠ read-set tables NOT present in {TARGET_SCHEMA} "
              f"(publish them first with 05_publish_dashboard_models.py): {missing_keep}")

    if not args.apply:
        print("\nDRY-RUN — nothing was dropped. Re-run with --apply to drop the above.")
        engine.dispose()
        return

    if missing_keep:
        print("\nABORTED — some read-set tables are missing in prod. Publish them before dropping.")
        engine.dispose()
        return

    token = f"DROP {len(to_drop)}"
    confirm = input(f"\nType exactly '{token}' to permanently drop these tables: ").strip()
    if confirm != token:
        print("Confirmation did not match. Aborted — nothing dropped.")
        engine.dispose()
        return

    dropped, failed = 0, []
    with engine.begin() as conn:
        for t in to_drop:
            try:
                conn.execute(text(f'DROP TABLE IF EXISTS "{TARGET_SCHEMA}"."{t}" CASCADE'))
                dropped += 1
            except Exception as ex:
                failed.append((t, str(ex)[:80]))

    print(f"\nDropped {dropped}/{len(to_drop)} tables from {TARGET_SCHEMA}.")
    if failed:
        print(f"Failed ({len(failed)}): {failed[:10]}")
    engine.dispose()


if __name__ == "__main__":
    main()
