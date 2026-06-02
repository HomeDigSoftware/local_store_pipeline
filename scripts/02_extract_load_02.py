"""
Step 2 (SQLAlchemy edition) — Extract all source tables from SQL Server → load to local Postgres (raw schema).
Run this script via Task Scheduler after 01_restore_backup.py completes.
When enabled, it first generates synthetic invoices in SQL Server so the daily load includes fresh simulated activity.

Key difference from 02_extract_load.py:
  - All database connections (both SQL Server and Postgres) go through SQLAlchemy engines.
  - pyodbc is used only as the underlying ODBC driver; no pyodbc API is called directly.
  - Table discovery uses sqlalchemy.inspect() instead of a raw INFORMATION_SCHEMA query.
  - The MAX(Recordingdate) query is executed through a SQLAlchemy connection context manager,
    which guarantees the connection is always released even if an exception is raised.

Install dependencies:
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

# ── Configuration ──────────────────────────────────────────────────────────────

# SQLAlchemy URL for SQL Server — uses pyodbc as the ODBC driver under the hood.
# URL.create() handles special characters in host/password safely.
MSSQL_URL = URL.create(
    drivername="mssql+pyodbc",
    username=os.environ["MSSQL_USER"],
    password=os.environ["MSSQL_PASSWORD"],
    host=os.environ["MSSQL_SERVER"],
    database=os.environ["MSSQL_DATABASE"],
    query={"driver": "ODBC Driver 17 for SQL Server"},
)

# SQLAlchemy URL for local Postgres
PG_URL = (
    f"postgresql://{os.environ['PG_USER']}:{os.environ['PG_PASSWORD']}"
    f"@{os.environ['PG_HOST']}:{os.environ['PG_PORT']}/{os.environ['PG_DATABASE']}"
)
PG_SCHEMA = "raw"

# Tables to skip (views or tables not present in the backup)
SKIP_TABLES = {
    "vw_pos_cash_receipts",
}

# sqlcmd parameters — used only for the BACKUP DATABASE command in save_backup()
MSSQL_SERVER   = os.environ["MSSQL_SERVER"]
MSSQL_DATABASE = os.environ["MSSQL_DATABASE"]
MSSQL_USER     = os.environ["MSSQL_USER"]
MSSQL_PASSWORD = os.environ["MSSQL_PASSWORD"]
BACKUP_FILE    = os.environ["BACKUP_FILE"]

ENABLE_SYNTHETIC_INVOICES = True
SYNTHETIC_INVOICE_COUNT  = 105
SYNTHETIC_MIN_LINES      = 1
SYNTHETIC_MAX_LINES      = 5
SYNTHETIC_CREDIT_RATE    = 0.22
SYNTHETIC_RETURN_RATE    = 0.03
SYNTHETIC_DISCOUNT_RATE  = 0.17
SYNTHETIC_UPDATE_INVENTORY = True
SYNTHETIC_SEED = 42
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

    Returns a YYYY-MM-DD string ready to pass to generate_synthetic_invoices.py --date.
    """
    if date_override:
        log.info("Date override provided via CLI: %s", date_override)
        return date_override

    # Candidate column names for the business date, in priority order.
    # Comparison is done on UPPER() so it is collation-independent.
    CANDIDATE_COLUMNS: list[str] = ["Recordingdate", "ReferenceDate", "ValueDate"]
    upper_candidates = ", ".join(f"'{c.upper()}'" for c in CANDIDATE_COLUMNS)

    try:
        with mssql_engine.connect() as conn:

            # ── Step 1: discover which candidate column actually exists ───────
            # Querying INFORMATION_SCHEMA is safe and avoids any hardcoded name
            # assumption.  UPPER() normalises the stored name so the comparison
            # is case-insensitive regardless of the DB collation setting.
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

            # ── Step 2: query the latest date using the discovered column ─────
            # Bracket-quoting [col_name] is the correct SQL Server way to escape
            # identifiers; col_name originates from INFORMATION_SCHEMA so it is
            # safe — not user-supplied input.
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

        # Table exists but contains no rows yet.
        log.warning("dbo.Documents has no rows — falling back to today.")
        return date.today().isoformat()

    except Exception as exc:
        log.warning("Could not resolve target date, falling back to today: %s", exc)
        return date.today().isoformat()


def run_synthetic_generation(
    date_override: str | None,
    mssql_engine: sqlalchemy.Engine,
) -> str:
    """Generate synthetic invoices into SQL Server for the resolved target date.

    Returns the target date string (YYYY-MM-DD) that was used.
    """
    if not ENABLE_SYNTHETIC_INVOICES:
        log.info("Synthetic invoice generation is disabled — skipping.")
        return _resolve_target_date(date_override, mssql_engine)

    script_path = Path(__file__).parent / "generate_synthetic_invoices.py"
    target_date = _resolve_target_date(date_override, mssql_engine)

    log.info("Synthetic invoices will be generated for: %s", target_date)

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

    log.info("Launching synthetic invoice generator...")
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
      1. Generate synthetic invoices for the target date.
      2. Copy every BASE TABLE from dbo (SQL Server) to raw schema (Postgres).
    """
    log.info("Creating SQL Server engine (mssql+pyodbc)...")
    mssql_engine = sqlalchemy.create_engine(MSSQL_URL, fast_executemany=True)

    # ── 1. Generate synthetic data BEFORE reading from SQL Server ─────────────
    target_date = run_synthetic_generation(date_override, mssql_engine)

    # ── 2. Discover tables via SQLAlchemy inspector ───────────────────────────
    log.info("Discovering tables in dbo schema...")
    inspector = inspect(mssql_engine)
    all_tables = inspector.get_table_names(schema="dbo")
    tables_to_load = [t for t in sorted(all_tables) if t not in SKIP_TABLES]
    log.info("Found %d tables to load.", len(tables_to_load))

    # ── 3. Connect to Postgres ────────────────────────────────────────────────
    log.info("Creating Postgres engine...")
    pg_engine = sqlalchemy.create_engine(PG_URL)

    with pg_engine.connect() as pg_conn:
        pg_conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {PG_SCHEMA}"))
        pg_conn.commit()

    # ── 4. Load each table ───────────────────────────────────────────────────
    failed: list[str] = []

    for table in tables_to_load:
        try:
            log.info("  Loading: %s  [target: %s]", table, target_date)

            # pd.read_sql accepts a SQLAlchemy engine directly.
            # Using text() makes the query explicit and avoids pandas warnings.
            df = pd.read_sql(
                text(f"SELECT * FROM dbo.[{table}]"),
                mssql_engine,
            )
            df.columns = [c.lower() for c in df.columns]  # normalize for Postgres

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

    # Engines are connection-pooled; explicit dispose releases all connections cleanly.
    mssql_engine.dispose()
    pg_engine.dispose()

    if failed:
        log.warning("Completed with skipped tables: %s", failed)
    else:
        log.info("All tables loaded successfully.")


def save_backup() -> None:
    """
    Overwrite the .bak file with the current DB state so tomorrow's restore
    includes today's synthetic data.

    Note: BACKUP DATABASE cannot be executed through a regular SQLAlchemy
    connection because SQL Server requires the statement to run outside of
    any open transaction.  sqlcmd (a separate process) handles this correctly.
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
        description="Extract SQL Server → Postgres (SQLAlchemy edition)"
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
