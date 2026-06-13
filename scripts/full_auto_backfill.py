# EXPERIMENTAL / SANDBOX orchestrator — does NOT replace 04_backfill_loop.py.
"""
full_auto_backfill.py — backfill loop WITH a dbt snapshot run integrated per
iteration, so a real historical inventory time-series is accumulated.

WHY THIS EXISTS
---------------
04_backfill_loop.py runs 02_extract_load_03.py N times, then runs 03 once at the
end. dbt is never called inside the loop, so the working fct_inventory_snapshot
model (which stamps current_date) can only ever capture ONE snapshot — today.

This sandbox interleaves a dbt run after every iteration:

    for each business date D:
        1. 02_extract_load_03.py   -> loads date D into local Postgres `raw`
        2. read MAX(business date) just generated
        3. dbt run --select +fct_inventory_snapshot_history
                   --vars '{"snapshot_date": "D"}'  --target dev
           -> rebuilds the upstream (staging + int_sales + int_inventory) from the
              raw state for date D, then APPENDS one snapshot row per item, stamped
              with the BUSINESS date D (not the wall clock).

The model fct_inventory_snapshot_history is incremental + guarded, so re-running
the same date is a no-op. After the loop, raw.fct_inventory_snapshot_history holds
one row per item per business day — the historical series.

Pair this with: models/marts/core/fct_inventory_snapshot_history.sql

FINAL DELIVERY TO SUPABASE (after the loop, steps 1-3)
------------------------------------------------------
The series is accumulated in DEV (local raw) because only local raw is updated per
iteration. To get EVERYTHING to Supabase, the loop is followed by:
  STEP 1  03_load_to_supabase.py                      local raw → Supabase raw
  STEP 2  dbt run --target prod --exclude <history>   build all prod models → store_pipeline
  STEP 3  copy raw.<history> (local) → Supabase store_pipeline.<history>
Step 3 is a direct table copy because the history CANNOT be rebuilt on prod
(Supabase raw only holds the final business date after step 1). Step 2 excludes the
history model so the prod build never overwrites the accumulated series.

IMPORTANT NOTES
---------------
* Target is DEV (local Postgres) for the per-iteration snapshot on purpose: only the
  local `raw` schema is updated per iteration, so only dev can accumulate the series.
* Because the per-iteration dbt builds models into local raw, STEP 1 (03) will also
  push those dev-built model tables to Supabase raw. That is cosmetic (prod dbt only
  reads declared sources) but if you want Supabase raw to stay sources-only, refine
  03 later to push a source allowlist.
* `+fct_inventory_snapshot_history` rebuilds the full ancestry every iteration for
  correctness (velocity/days-of-cover depend on the sales chain). That is heavier
  than a normal run; for a quick test, narrow DBT_SELECT if you only need stock
  levels without recomputed velocity.
* This script does NOT modify 04_backfill_loop.py, 02, 03, or the working
  fct_inventory_snapshot model. Test here first; promote later if it behaves.

PREREQUISITES (same as 04)
  - 01_restore_backup.py run first with the original .bak
  - .env present and configured
"""

import sys
import time
import json
import subprocess
import logging
import os
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import pandas as pd
import sqlalchemy
from sqlalchemy import text
from sqlalchemy.engine import URL

# ── Configuration ──────────────────────────────────────────────────────────────
MSSQL_URL = URL.create(
    drivername="mssql+pyodbc",
    username=os.environ["MSSQL_USER"],
    password=os.environ["MSSQL_PASSWORD"],
    host=os.environ["MSSQL_SERVER"],
    database=os.environ["MSSQL_DATABASE"],
    query={"driver": "ODBC Driver 17 for SQL Server"},
)

PROJECT_ROOT = Path(__file__).parent.parent          # dbt project root (has dbt_project.yml)
SCRIPT_02 = Path(__file__).parent / "02_extract_load_03.py"
SCRIPT_03 = Path(__file__).parent / "03_load_to_supabase.py"

DBT_TARGET = "dev"                                   # accumulate locally; switch consciously
DBT_SELECT = "+fct_inventory_snapshot_history"       # ancestry + the incremental snapshot

# ── Final delivery to Supabase (steps 1-3) ──
DELIVER_TO_SUPABASE_AT_END = True                    # run the 3-step delivery after the loop
PROD_TARGET   = "prod"                                # dbt target for the Supabase build
HISTORY_MODEL = "fct_inventory_snapshot_history"     # the accumulated series model/table
PROD_SCHEMA   = "store_pipeline"                      # Supabase schema for prod dbt models
# ───────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(Path(__file__).parent / "pipeline.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


def _get_current_max_date(engine: sqlalchemy.Engine) -> date | None:
    """MAX business date from dbo.Documents (dynamic column discovery)."""
    candidates = ["Recordingdate", "ReferenceDate", "ValueDate"]
    upper_candidates = ", ".join(f"'{c.upper()}'" for c in candidates)
    try:
        with engine.connect() as conn:
            col_row = conn.execute(text(f"""
                SELECT TOP 1 COLUMN_NAME
                FROM   INFORMATION_SCHEMA.COLUMNS
                WHERE  TABLE_SCHEMA = 'dbo'
                  AND  TABLE_NAME   = 'Documents'
                  AND  UPPER(COLUMN_NAME) IN ({upper_candidates})
                ORDER BY ORDINAL_POSITION
            """)).fetchone()
            if col_row is None:
                return None
            col_name: str = col_row[0]
            max_row = conn.execute(
                text(f"SELECT CAST(MAX([{col_name}]) AS DATE) FROM dbo.Documents")
            ).fetchone()
            return max_row[0] if max_row and max_row[0] else None
    except Exception as exc:
        log.error("Could not query MAX date from dbo.Documents: %s", exc)
        return None


def _run_extract_load(iteration: int, total: int) -> bool:
    """Run one 02_extract_load_03.py iteration (loads MAX+1 into raw)."""
    log.info("━" * 60)
    log.info("Iteration %d / %d  —  extract + load", iteration, total)
    log.info("━" * 60)
    result = subprocess.run([sys.executable, str(SCRIPT_02)])
    if result.returncode != 0:
        log.error("02_extract_load_03.py exited with code %d on iteration %d.",
                  result.returncode, iteration)
        return False
    return True


def _run_dbt_snapshot(business_date: date) -> bool:
    """
    Append the snapshot for `business_date` via the incremental history model.
    Runs from the dbt project root using `uv run dbt`.
    """
    cmd = [
        "uv", "run", "dbt", "run",
        "--select", DBT_SELECT,
        "--vars", json.dumps({"snapshot_date": business_date.isoformat()}),
        "--target", DBT_TARGET,
    ]
    log.info("dbt snapshot  —  business_date=%s  select=%s  target=%s",
             business_date, DBT_SELECT, DBT_TARGET)
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if result.returncode != 0:
        log.error("dbt run failed (code %d) for snapshot_date=%s.",
                  result.returncode, business_date)
        return False
    return True


def _step1_push_sources_to_supabase() -> bool:
    """STEP 1/3 — local raw → Supabase raw (existing 03 script, all base tables)."""
    log.info("STEP 1/3 — 03_load_to_supabase.py  (local raw → Supabase raw)")
    result = subprocess.run([sys.executable, str(SCRIPT_03)])
    if result.returncode != 0:
        log.error("03_load_to_supabase.py exited with code %d.", result.returncode)
        return False
    return True


def _step2_build_prod_models() -> bool:
    """STEP 2/3 — build all prod models in store_pipeline, EXCLUDING the history
    model (so prod does not overwrite the accumulated series with a single date)."""
    cmd = ["uv", "run", "dbt", "run", "--target", PROD_TARGET, "--exclude", HISTORY_MODEL]
    log.info("STEP 2/3 — dbt build on prod  (exclude %s → %s)", HISTORY_MODEL, PROD_SCHEMA)
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if result.returncode != 0:
        log.error("dbt prod build failed (code %d).", result.returncode)
        return False
    return True


def _step3_copy_history_to_supabase() -> bool:
    """STEP 3/3 — copy the accumulated history table from local raw → Supabase
    store_pipeline (it cannot be rebuilt on prod, so we copy the finished table)."""
    log.info("STEP 3/3 — copy raw.%s (local) → Supabase %s.%s",
             HISTORY_MODEL, PROD_SCHEMA, HISTORY_MODEL)
    local_engine = supabase_engine = None
    try:
        local_url = (
            f"postgresql://{os.environ['PG_USER']}:{os.environ['PG_PASSWORD']}"
            f"@{os.environ['PG_HOST']}:{os.environ['PG_PORT']}/{os.environ['PG_DATABASE']}"
        )
        local_engine = sqlalchemy.create_engine(local_url)
        supabase_engine = sqlalchemy.create_engine(os.environ["SUPABASE_URL"])

        with supabase_engine.connect() as conn:
            conn.execute(sqlalchemy.text(f"CREATE SCHEMA IF NOT EXISTS {PROD_SCHEMA}"))
            conn.commit()

        df = pd.read_sql_table(HISTORY_MODEL, local_engine, schema="raw")
        df.to_sql(
            HISTORY_MODEL,
            supabase_engine,
            schema=PROD_SCHEMA,
            if_exists="replace",
            index=False,
            chunksize=2000,
        )
        distinct_dates = df["snapshot_date"].nunique() if "snapshot_date" in df.columns else -1
        log.info("  Copied %d rows (%d distinct snapshot_date) → Supabase %s.%s",
                 len(df), distinct_dates, PROD_SCHEMA, HISTORY_MODEL)
        return True
    except Exception as exc:
        log.error("History copy to Supabase failed: %s", exc)
        return False
    finally:
        if local_engine is not None:
            local_engine.dispose()
        if supabase_engine is not None:
            supabase_engine.dispose()


def _step4_revalidate_website() -> None:
    """STEP 4/4 — flush the website dashboard cache (best-effort, never fails the run).
    Fires AFTER the prod build so the dashboard re-fetches fresh store_pipeline data."""
    log.info("STEP 4/4 — website cache revalidate (best-effort)")
    subprocess.run([sys.executable, str(Path(__file__).parent / "revalidate_website.py")])


def _deliver_to_supabase() -> bool:
    """Run the full delivery so everything ends up on Supabase, then flush the site cache."""
    log.info("═" * 60)
    log.info("Final delivery to Supabase (steps 1-3) + website revalidate (step 4)")
    log.info("═" * 60)
    ok = (
        _step1_push_sources_to_supabase()
        and _step2_build_prod_models()
        and _step3_copy_history_to_supabase()
    )
    if ok:
        _step4_revalidate_website()   # only after store_pipeline is fully rebuilt
    return ok


def main() -> None:
    print()
    print("╔" + "═" * 58 + "╗")
    print("║  full_auto_backfill — backfill + per-day dbt snapshot   ║")
    print("╚" + "═" * 58 + "╝")

    engine = sqlalchemy.create_engine(MSSQL_URL)
    current_max = _get_current_max_date(engine)
    today = date.today()

    if current_max is not None:
        next_date = current_max + timedelta(days=1)
        fill_days = max((today - current_max).days - 1, 0)
        print(f"\n  Current MAX date in DB   : {current_max}")
        print(f"  Next date to generate    : {next_date}")
        print(f"  Today                    : {today}")
        print(f"  Days needed to reach today: {fill_days}")
    else:
        print("\n  Could not determine current MAX date.")
        fill_days = 0

    print(f"\n  dbt target   : {DBT_TARGET}")
    print(f"  dbt select   : {DBT_SELECT}")

    print()
    user_input = input(
        "  Enter number of days to run  [press Enter to run until today]: "
    ).strip()

    if user_input == "":
        if fill_days <= 0:
            print("\n  DB is already up to date. Nothing to do.\n")
            engine.dispose()
            return
        iterations = fill_days
        mode_label = f"auto — run until today ({iterations} iterations)"
    else:
        try:
            iterations = int(user_input)
            if iterations <= 0:
                print("  Error: number of days must be greater than zero.")
                engine.dispose()
                return
            mode_label = f"manual — {iterations} iteration(s)"
        except ValueError:
            print(f"  Error: '{user_input}' is not a valid number.")
            engine.dispose()
            return

    print(f"\n  Mode      : {mode_label}")
    print(f"  Iterations: {iterations}")
    print("\n  Starting in 3 seconds … (Ctrl+C to abort)\n")
    time.sleep(3)

    log.info("full_auto_backfill started — %s", mode_label)
    success_count = 0

    for i in range(1, iterations + 1):
        # 1. extract + load business date MAX+1 into local raw
        if not _run_extract_load(i, iterations):
            log.error("Aborted after %d successful iteration(s).", success_count)
            break

        # 2. find the business date that was just generated
        business_date = _get_current_max_date(engine)
        if business_date is None:
            log.error("Could not resolve business date after iteration %d — skipping dbt.", i)
            break

        # 3. append the snapshot for that business date (rebuilds ancestry + appends)
        if not _run_dbt_snapshot(business_date):
            log.error("Aborted after %d successful iteration(s) (dbt failure).", success_count)
            break

        success_count += 1

    engine.dispose()

    print()
    print("╔" + "═" * 58 + "╗")
    log.info("full_auto_backfill finished: %d / %d iterations succeeded.",
             success_count, iterations)
    print("╚" + "═" * 58 + "╝")
    print()

    if success_count < iterations:
        log.warning("Skipping Supabase delivery — backfill did not complete successfully.")
        return

    if DELIVER_TO_SUPABASE_AT_END:
        if not _deliver_to_supabase():
            log.error("Supabase delivery did not complete. Local data is intact.")
            return

    log.info(
        "Done. Verify — local:  select snapshot_date, count(*) "
        "from raw.fct_inventory_snapshot_history group by 1 order by 1;  |  "
        "Supabase: store_pipeline.fct_inventory_snapshot_history"
    )


if __name__ == "__main__":
    main()
