"""
Backfill loop — runs 02_extract_load_02.py repeatedly to fill historical date gaps.

When prompted:
  - Enter a number → runs exactly that many iterations
  - Press Enter (empty) → calculates days from current MAX to today and runs that many

Each iteration:
  1. 02_extract_load_02.py reads MAX(Recordingdate) from SQL Server
  2. Generates synthetic invoices for MAX + 1
  3. Loads all tables to Postgres
  4. Saves the .bak so the next iteration picks up the new MAX

Prerequisites:
  - 01_restore_backup.py must have been run first with the original .bak
  - .env must be present and correctly configured
"""

import sys
import time
import subprocess
import logging
import os
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

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

SCRIPT_02 = Path(__file__).parent / "02_extract_load_03.py"
SCRIPT_03 = Path(__file__).parent / "03_load_to_supabase.py"
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
    """
    Query the current MAX business date from dbo.Documents using dynamic
    column discovery (same logic as _resolve_target_date in 02_extract_load_02.py).
    Returns None if the column or table cannot be found.
    """
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


def _run_one_iteration(iteration: int, total: int) -> bool:
    """
    Run a single iteration of 02_extract_load_02.py.
    Output streams directly to the console (not captured) so the user sees
    live progress.  Returns True on success, False on failure.
    """
    log.info("━" * 60)
    log.info("Iteration %d / %d", iteration, total)
    log.info("━" * 60)

    result = subprocess.run([sys.executable, str(SCRIPT_02)])

    if result.returncode != 0:
        log.error("02_extract_load_02.py exited with code %d on iteration %d.",
                  result.returncode, iteration)
        return False
    return True


def main() -> None:
    print()
    print("╔" + "═" * 58 + "╗")
    print("║  Backfill Loop — store_pipeline                        ║")
    print("╚" + "═" * 58 + "╝")

    # ── Show current DB state ────────────────────────────────────────────────
    engine = sqlalchemy.create_engine(MSSQL_URL)
    current_max = _get_current_max_date(engine)
    engine.dispose()

    today = date.today()

    if current_max is not None:
        next_date  = current_max + timedelta(days=1)
        gap_days   = (today - current_max).days          # days including today
        fill_days  = max(gap_days - 1, 0)                 # exclude today itself
        print(f"\n  Current MAX date in DB  : {current_max}")
        print(f"  Next date to generate   : {next_date}")
        print(f"  Today                   : {today}")
        print(f"  Days needed to reach today : {fill_days}")
    else:
        print(f"\n  Could not determine current MAX date.")
        print(f"  Today: {today}")
        fill_days = 0

    # ── Prompt user ───────────────────────────────────────────────────────────
    print()
    user_input = input(
        "  Enter number of days to run  [press Enter to run until today]: "
    ).strip()

    if user_input == "":
        if fill_days <= 0:
            print("\n  DB is already up to date. Nothing to do.\n")
            return
        iterations = fill_days
        mode_label = f"auto — run until today ({iterations} iterations)"
    else:
        try:
            iterations = int(user_input)
            if iterations <= 0:
                print("  Error: number of days must be greater than zero.")
                return
            mode_label = f"manual — {iterations} iteration(s)"
        except ValueError:
            print(f"  Error: '{user_input}' is not a valid number.")
            return

    print(f"\n  Mode      : {mode_label}")
    print(f"  Iterations: {iterations}")
    print("\n  Starting in 3 seconds … (Ctrl+C to abort)\n")
    time.sleep(3)

    # ── Main loop ─────────────────────────────────────────────────────────────
    log.info("Backfill loop started — %s", mode_label)
    success_count = 0

    for i in range(1, iterations + 1):
        ok = _run_one_iteration(i, iterations)
        if ok:
            success_count += 1
            
        else:
            log.error("Backfill loop aborted after %d successful iteration(s).", success_count)
            break

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    print("╔" + "═" * 58 + "╗")
    log.info("Backfill finished: %d / %d iterations succeeded.", success_count, iterations)
    print("╚" + "═" * 58 + "╝")
    print()

    if success_count < iterations:
        log.warning("Skipping Supabase load — backfill did not complete successfully.")
        return

    log.info("Running 03_load_to_supabase.py …")
    result = subprocess.run([sys.executable, str(SCRIPT_03)])

    if result.returncode != 0:
        log.error("03_load_to_supabase.py exited with code %d.", result.returncode)
        return

if __name__ == "__main__":
    main()
