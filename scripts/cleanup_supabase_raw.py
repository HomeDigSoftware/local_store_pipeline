# NEW — safe cleanup of excess tables in Supabase `raw`. DRY-RUN by default.
"""
cleanup_supabase_raw.py — drop the excess tables from Supabase `raw`.

Diagnosis (SUPABASE_LOAD_REDUCTION_PLAN.md §1b) found 539 tables in Supabase `raw`
(POS tables never used by dbt + dev model tables pushed by mistake). They cause a
PostgREST re-introspection storm. This script removes everything in `raw` EXCEPT the
8 source tables dbt actually needs.

SAFETY
------
* DRY-RUN by default — prints what WOULD be dropped and changes nothing.
* `--apply` actually drops, and ONLY after you type the exact confirmation string.
* Touches ONLY schema `raw`. Never touches `store_pipeline`.
* Never drops a table in KEEP (the allowlist).

⚠️ RUN ORDER — do these FIRST, or the dashboard will break:
   1. Point the Next.js dashboard at `store_pipeline.rpt_*` (NOT `raw.*`).
   2. Switch the loader to 03_load_to_supabase_allowlist.py.
   3. Then run this cleanup.

Usage:
   uv run python scripts/cleanup_supabase_raw.py            # dry-run (safe)
   uv run python scripts/cleanup_supabase_raw.py --apply    # drops, with confirmation
"""

import sys
import os
import argparse
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import sqlalchemy as sa
from sqlalchemy import text

SUPABASE_URL = os.environ["SUPABASE_URL"]
TARGET_SCHEMA = "raw"

# Must match ALLOWLIST in 03_load_to_supabase_allowlist.py.
KEEP = {
    "documents",
    "documentlines",
    "receiptlines",
    "inventory",
    "items",
    "itemtypes",
    "employeesattendance",
    "employeesselection_byentrance",
}


def main() -> None:
    ap = argparse.ArgumentParser(description="Drop excess tables from Supabase raw (dry-run by default).")
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
    print(f"KEEP (allowlist):  {len(KEEP)}  ->  {sorted(KEEP)}")
    print(f"DROP candidates :  {len(to_drop)}")
    for t in to_drop[:60]:
        print("   -", t)
    if len(to_drop) > 60:
        print(f"   ... (+{len(to_drop) - 60} more)")
    if missing_keep:
        print(f"\n⚠ allowlist tables NOT present in Supabase {TARGET_SCHEMA}: {missing_keep}")

    if not args.apply:
        print("\nDRY-RUN — nothing was dropped. Re-run with --apply to drop the above.")
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
