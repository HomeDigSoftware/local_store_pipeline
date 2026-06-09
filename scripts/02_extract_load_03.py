"""
Step 2 v03 — Extract SQL Server → Postgres with automatic inventory replenishment.

Extends 02_extract_load_02.py with a REPLENISHMENT CYCLE:
  Every REPLENISHMENT_INTERVAL_DAYS days (default 6, i.e. roughly every 5–7 days)
  the generate_synthetic_invoices_03.py script is called with --replenish-inventory,
  simulating a merchandise delivery that the owner placed after the previous cycle.

  The replenishment day is determined deterministically from the target date:
    days_since_anchor % REPLENISHMENT_INTERVAL_DAYS == 0
  where the anchor is the earliest date in the original backup data (2021-03-26).
  Because the calculation is based purely on the calendar date, it is reproducible
  across backfill runs and normal daily runs without any extra state.

Replenishment parameters (configurable at the top of the file):
  REPLENISHMENT_INTERVAL_DAYS  — cadence in days (default 6).
  REPLENISHMENT_WINDOW_DAYS    — look-back window for sold-qty calculation (default 7).
  RESTOCK_MULTIPLIER           — qty_sold × factor ordered (default 1.2 = 20 % buffer).
  MIN_RESTOCK_QTY              — minimum units added even if nothing sold (default 10).

All other behaviour (date resolution, table discovery, Postgres load, backup) is
identical to 02_extract_load_02.py.  That file is unchanged.

Install dependencies (same as _02):
  uv add pyodbc pandas sqlalchemy psycopg2-binary
"""

import sys
import argparse
import logging
import subprocess
import os
from datetime import date, timedelta
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import pandas as pd
import sqlalchemy
from sqlalchemy import inspect, text
from sqlalchemy.engine import URL

# ── Connection configuration ───────────────────────────────────────────────────

MSSQL_URL = URL.create(
    drivername="mssql+pyodbc",
    username=os.environ["MSSQL_USER"],
    password=os.environ["MSSQL_PASSWORD"],
    host=os.environ["MSSQL_SERVER"],
    database=os.environ["MSSQL_DATABASE"],
    query={"driver": "ODBC Driver 17 for SQL Server"},
)

PG_URL = (
    f"postgresql://{os.environ['PG_USER']}:{os.environ['PG_PASSWORD']}"
    f"@{os.environ['PG_HOST']}:{os.environ['PG_PORT']}/{os.environ['PG_DATABASE']}"
)
PG_SCHEMA = "raw"

SKIP_TABLES = {
    "vw_pos_cash_receipts",
}

MSSQL_SERVER   = os.environ["MSSQL_SERVER"]
MSSQL_DATABASE = os.environ["MSSQL_DATABASE"]
MSSQL_USER     = os.environ["MSSQL_USER"]
MSSQL_PASSWORD = os.environ["MSSQL_PASSWORD"]
BACKUP_FILE    = os.environ["BACKUP_FILE"]

# ── Synthetic invoice generation ───────────────────────────────────────────────

ENABLE_SYNTHETIC_INVOICES = True
SYNTHETIC_INVOICE_COUNT   = 105
SYNTHETIC_MIN_LINES       = 1
SYNTHETIC_MAX_LINES       = 5
SYNTHETIC_CREDIT_RATE     = 0.22
SYNTHETIC_RETURN_RATE     = 0.03
SYNTHETIC_DISCOUNT_RATE   = 0.17
SYNTHETIC_UPDATE_INVENTORY = True
SYNTHETIC_SEED             = 42

# ── Replenishment configuration (NEW in v03) ───────────────────────────────────
#
# REPLENISHMENT_INTERVAL_DAYS:
#   How often (in calendar days) a stock delivery is simulated.
#   6 keeps the cadence in the realistic 5–7 day range and divides evenly
#   across weeks of varying length.
#
# REPLENISHMENT_ANCHOR_DATE:
#   Reference date used to align the cycle.  Set to the earliest date in the
#   original backup so the first delivery falls naturally at day 6.
#
# REPLENISHMENT_WINDOW_DAYS:
#   How many days of sales history to sum when calculating restock quantities.
#   Should be >= REPLENISHMENT_INTERVAL_DAYS so the full selling period is covered.
#
# RESTOCK_MULTIPLIER:
#   The owner orders more than was sold (covers spoilage, growth, safety stock).
#   1.2 = order 20 % above the previous period's consumption.
#
# MIN_RESTOCK_QTY:
#   Minimum units added per item even if it had zero sales.
#   Prevents slow-moving SKUs from permanently dropping out of the item pool.

REPLENISHMENT_INTERVAL_DAYS  = 6
REPLENISHMENT_ANCHOR_DATE    = date(2021, 3, 26)   # earliest date in original backup
REPLENISHMENT_WINDOW_DAYS    = 7
RESTOCK_MULTIPLIER           = 1.2
MIN_RESTOCK_QTY              = 10.0

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


def _resolve_target_date(date_override: str | None, mssql_engine: sqlalchemy.Engine) -> str:
    """
    Determine the date for which synthetic invoices should be generated.

    Priority:
      1. date_override — value passed via CLI argument (YYYY-MM-DD string).
      2. MAX(<date_col>) + 1 day — the date column is discovered dynamically from
         INFORMATION_SCHEMA so the function survives DB schema variations.
      3. date.today() — last-resort fallback when no date column can be found or
         the table is empty.

    The POS source stores business dates as VARCHAR(8) 'YYYYMMDD' strings.
    SQL Server can CAST that format directly to DATE without a CONVERT step.

    Returns a YYYY-MM-DD string ready to pass to generate_synthetic_invoices_03.py --date.
    """
    if date_override:
        log.info("Date override provided via CLI: %s", date_override)
        return date_override

    CANDIDATE_COLUMNS: list[str] = ["Recordingdate", "ReferenceDate", "ValueDate"]
    upper_candidates = ", ".join(f"'{c.upper()}'" for c in CANDIDATE_COLUMNS)

    try:
        with mssql_engine.connect() as conn:
            discovery_sql = text(f"""
                SELECT TOP 1 COLUMN_NAME
                FROM   INFORMATION_SCHEMA.COLUMNS
                WHERE  TABLE_SCHEMA = 'dbo'
                  AND  TABLE_NAME   = 'Documents'
                  AND  UPPER(COLUMN_NAME) IN ({upper_candidates})
                ORDER BY ORDINAL_POSITION
            """)
            col_row = conn.execute(discovery_sql).fetchone()

            if col_row is None:
                log.warning(
                    "None of the known date columns (%s) were found in dbo.Documents. "
                    "Falling back to today.",
                    ", ".join(CANDIDATE_COLUMNS),
                )
                return date.today().isoformat()

            col_name: str = col_row[0]
            log.info("Discovered business-date column in dbo.Documents: [%s]", col_name)

            max_row = conn.execute(
                text(f"SELECT CAST(MAX([{col_name}]) AS DATE) FROM dbo.Documents")
            ).fetchone()

        if max_row is not None and max_row[0] is not None:
            last_date: date = max_row[0]
            next_date = last_date + timedelta(days=1)
            log.info(
                "MAX([%s]) = %s  →  generating for next day: %s",
                col_name,
                last_date,
                next_date,
            )
            return next_date.isoformat()

        log.warning("dbo.Documents has no rows — falling back to today.")
        return date.today().isoformat()

    except Exception as exc:
        log.warning("Could not resolve target date, falling back to today: %s", exc)
        return date.today().isoformat()


def _is_replenishment_day(target: date) -> bool:
    """
    Return True when `target` falls on a replenishment cycle day.

    The cycle is anchored at REPLENISHMENT_ANCHOR_DATE and repeats every
    REPLENISHMENT_INTERVAL_DAYS calendar days.  The calculation is purely
    arithmetic — no state file, no DB query — so it is always reproducible.

    Examples with interval=6 and anchor=2021-03-26:
      2021-04-01  (day  6) → True   delivery 1
      2021-04-07  (day 12) → True   delivery 2
      2021-04-08  (day 13) → False
      ...
    """
    days_since_anchor = (target - REPLENISHMENT_ANCHOR_DATE).days
    if days_since_anchor <= 0:
        return False                        # before or on the anchor — skip
    return days_since_anchor % REPLENISHMENT_INTERVAL_DAYS == 0


def run_synthetic_generation(
    date_override: str | None,
    mssql_engine: sqlalchemy.Engine,
) -> str:
    """
    Generate synthetic invoices into SQL Server for the resolved target date.
    On replenishment days, passes --replenish-inventory to the generator so
    dbo.Inventory is topped up before the invoices are created.

    Returns the target date string (YYYY-MM-DD) that was used.
    """
    if not ENABLE_SYNTHETIC_INVOICES:
        log.info("Synthetic invoice generation is disabled — skipping.")
        return _resolve_target_date(date_override, mssql_engine)

    # Use generate_synthetic_invoices_03.py (v03) which supports replenishment.
    script_path = Path(__file__).parent / "generate_synthetic_invoices_03.py"
    target_date = _resolve_target_date(date_override, mssql_engine)
    target_date_obj = date.fromisoformat(target_date)

    replenish = _is_replenishment_day(target_date_obj)
    if replenish:
        log.info(
            "Replenishment day detected for %s "
            "(every %d days from anchor %s) — inventory will be restocked.",
            target_date,
            REPLENISHMENT_INTERVAL_DAYS,
            REPLENISHMENT_ANCHOR_DATE,
        )
    else:
        log.info("Synthetic invoices will be generated for: %s (no replenishment today)", target_date)

    command = [
        sys.executable,
        str(script_path),
        "--date",           target_date,
        "--invoice-count",  str(SYNTHETIC_INVOICE_COUNT),
        "--min-lines",      str(SYNTHETIC_MIN_LINES),
        "--max-lines",      str(SYNTHETIC_MAX_LINES),
        "--credit-rate",    str(SYNTHETIC_CREDIT_RATE),
        "--return-rate",    str(SYNTHETIC_RETURN_RATE),
        "--discount-rate",  str(SYNTHETIC_DISCOUNT_RATE),
        "--seed",           str(SYNTHETIC_SEED),
        "--commit",
    ]
    if SYNTHETIC_UPDATE_INVENTORY:
        command.append("--update-inventory")
    if replenish:
        command.extend([
            "--replenish-inventory",
            "--replenish-window-days", str(REPLENISHMENT_WINDOW_DAYS),
            "--restock-multiplier",    str(RESTOCK_MULTIPLIER),
            "--min-restock-qty",       str(MIN_RESTOCK_QTY),
        ])

    log.info("Launching synthetic invoice generator (v03)...")
    result = subprocess.run(command, capture_output=True, text=True)

    if result.returncode != 0:
        log.error("Synthetic invoice generation failed.\n%s", result.stderr.strip())
        raise RuntimeError("Synthetic invoice generation failed.")

    for line in result.stdout.splitlines():
        log.info("  synthetic: %s", line)

    return target_date


def extract_and_load(date_override: str | None = None) -> None:
    """
    Main ETL function:
      1. Generate synthetic invoices (with replenishment when applicable).
      2. Copy every BASE TABLE from dbo (SQL Server) to raw schema (Postgres).
    """
    log.info("Creating SQL Server engine (mssql+pyodbc)...")
    mssql_engine = sqlalchemy.create_engine(MSSQL_URL, fast_executemany=True)

    target_date = run_synthetic_generation(date_override, mssql_engine)

    log.info("Discovering tables in dbo schema...")
    inspector = inspect(mssql_engine)
    all_tables = inspector.get_table_names(schema="dbo")
    tables_to_load = [t for t in sorted(all_tables) if t not in SKIP_TABLES]
    log.info("Found %d tables to load.", len(tables_to_load))

    log.info("Creating Postgres engine...")
    pg_engine = sqlalchemy.create_engine(PG_URL)

    with pg_engine.connect() as pg_conn:
        pg_conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {PG_SCHEMA}"))
        pg_conn.commit()

    failed: list[str] = []

    for table in tables_to_load:
        try:
            log.info("  Loading: %s  [target: %s]", table, target_date)
            df = pd.read_sql(
                text(f"SELECT * FROM dbo.[{table}]"),
                mssql_engine,
            )
            df.columns = [c.lower() for c in df.columns]
            df['_pipeline_loaded_at'] = pd.Timestamp.now() 
            df.to_sql(
                table.lower(),
                pg_engine,
                schema=PG_SCHEMA,
                if_exists="replace",
                index=False,
                chunksize=5000,
            )
            log.info("  Done: %s — %s rows  [target: %s]", table, f"{len(df):,}", target_date)

        except Exception as exc:
            log.warning("  SKIPPED: %s — %s  [target: %s]", table, exc, target_date)
            failed.append(table)

    mssql_engine.dispose()
    pg_engine.dispose()

    if failed:
        log.warning("Completed with skipped tables: %s", failed)
    else:
        log.info("All tables loaded successfully.")


def save_backup() -> None:
    """
    Overwrite the .bak file with the current DB state so tomorrow's restore
    includes today's synthetic data (and any replenishment applied today).
    """
    Path(BACKUP_FILE).parent.mkdir(parents=True, exist_ok=True)

    sql = (
        f"BACKUP DATABASE [{MSSQL_DATABASE}] "
        f"TO DISK=N'{BACKUP_FILE}' "
        f"WITH FORMAT, INIT, COMPRESSION, STATS=10;"
    )

    log.info("Saving SQL Server backup to: %s", BACKUP_FILE)
    result = subprocess.run(
        ["sqlcmd", "-S", MSSQL_SERVER, "-U", MSSQL_USER, "-P", MSSQL_PASSWORD, "-Q", sql],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        log.error("SQL Server backup failed.\n%s", result.stderr.strip())
        raise RuntimeError("SQL Server backup failed.")

    log.info("Backup saved successfully.\n%s", result.stdout.strip())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract SQL Server → Postgres v03 (SQLAlchemy + inventory replenishment)"
    )
    parser.add_argument(
        "date",
        nargs="?",
        default=None,
        metavar="YYYY-MM-DD",
        help=(
            "Target date for synthetic invoices (e.g. 2026-03-21). "
            "If omitted, uses MAX(Recordingdate)+1 from dbo.Documents."
        ),
    )
    args = parser.parse_args()

    extract_and_load(date_override=args.date)
    save_backup()
