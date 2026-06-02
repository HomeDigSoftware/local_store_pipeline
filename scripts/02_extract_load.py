"""
Step 2 — Extract all source tables from SQL Server → load to local Postgres (raw schema).
Run this script via Task Scheduler after 01_restore_backup.py completes.
When enabled, it first generates synthetic invoices in SQL Server so the daily load includes fresh simulated activity.

Install dependencies:
  uv add pyodbc pandas sqlalchemy psycopg2-binary
"""

import sys
import argparse
import logging
import subprocess
import os
from datetime import date, timedelta
import pyodbc
import pandas as pd
import sqlalchemy
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# ── Configuration ──────────────────────────────────────────────────────────────
MSSQL_SERVER   = os.environ["MSSQL_SERVER"]
MSSQL_DATABASE = os.environ["MSSQL_DATABASE"]
MSSQL_USER     = os.environ["MSSQL_USER"]
MSSQL_PASSWORD = os.environ["MSSQL_PASSWORD"]
BACKUP_FILE    = os.environ["BACKUP_FILE"]

MSSQL_CONN_STR = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    f"SERVER={MSSQL_SERVER};"
    f"DATABASE={MSSQL_DATABASE};"
    f"UID={MSSQL_USER};PWD={MSSQL_PASSWORD};"
)

PG_URL    = (
    f"postgresql://{os.environ['PG_USER']}:{os.environ['PG_PASSWORD']}"
    f"@{os.environ['PG_HOST']}:{os.environ['PG_PORT']}/{os.environ['PG_DATABASE']}"
)
PG_SCHEMA = "raw"

# Tables to skip (views or tables that don't exist in the backup)
SKIP_TABLES = {
    "vw_pos_cash_receipts",
}

ENABLE_SYNTHETIC_INVOICES = True
SYNTHETIC_INVOICE_COUNT = 35
SYNTHETIC_MIN_LINES = 1
SYNTHETIC_MAX_LINES = 5
SYNTHETIC_CREDIT_RATE = 0.22
SYNTHETIC_RETURN_RATE = 0.03
SYNTHETIC_DISCOUNT_RATE = 0.17
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


def run_synthetic_generation(date_override: str | None = None):
    if not ENABLE_SYNTHETIC_INVOICES:
        log.info("Synthetic invoice generation is disabled.")
        return

    script_path = Path(__file__).parent / "generate_synthetic_invoices.py"

    # Use the day after the last recordingdate in SQL Server so data is always continuous
    if date_override:
        target_date = date_override
        log.info("Using overridden date for synthetic generation: %s", target_date)
    else:   
        try:
            _conn = pyodbc.connect(MSSQL_CONN_STR)
            _cur = _conn.cursor()
            _cur.execute("SELECT CAST(MAX(Recordingdate) AS DATE) FROM dbo.Documents")
            _row = _cur.fetchone()
            _conn.close()
            if _row and _row[0]:
                target_date = (_row[0] + timedelta(days=1)).isoformat()
            else:
                target_date = date.today().isoformat()
        except Exception as _e:
            log.warning("Could not query MAX(recordingdate), falling back to today: %s", _e)
            target_date = date.today().isoformat()

    log.info("Synthetic invoices will be generated for: %s", target_date)
    command = [
        sys.executable,
        str(script_path),
        "--date",
        target_date,
        "--invoice-count",
        str(SYNTHETIC_INVOICE_COUNT),
        "--min-lines",
        str(SYNTHETIC_MIN_LINES),
        "--max-lines",
        str(SYNTHETIC_MAX_LINES),
        "--credit-rate",
        str(SYNTHETIC_CREDIT_RATE),
        "--return-rate",
        str(SYNTHETIC_RETURN_RATE),
        "--discount-rate",
        str(SYNTHETIC_DISCOUNT_RATE),
        "--seed",
        str(SYNTHETIC_SEED),
        "--commit",
    ]
    if SYNTHETIC_UPDATE_INVENTORY:
        command.append("--update-inventory")

    log.info("Generating synthetic invoices before extraction...")
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        log.error("Synthetic invoice generation failed.\n%s", result.stderr.strip())
        raise RuntimeError("Synthetic invoice generation failed.")

    for line in result.stdout.splitlines():
        log.info("  synthetic: %s", line)


def extract_and_load(date_override: str | None = None):
    run_synthetic_generation(date_override)

    log.info("Connecting to SQL Server...")
    mssql = pyodbc.connect(MSSQL_CONN_STR)

    log.info("Connecting to local Postgres...")
    pg_engine = sqlalchemy.create_engine(PG_URL)

    # Create raw schema if it doesn't exist
    with pg_engine.connect() as conn:
        conn.execute(sqlalchemy.text(f"CREATE SCHEMA IF NOT EXISTS {PG_SCHEMA}"))
        conn.commit()

    # Auto-discover all BASE TABLEs in dbo schema
    cursor = mssql.cursor()
    cursor.execute(
        "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_SCHEMA='dbo' AND TABLE_TYPE='BASE TABLE' "
        "ORDER BY TABLE_NAME"
    )
    all_tables = [row.TABLE_NAME for row in cursor.fetchall()]
    tables_to_load = [t for t in all_tables if t not in SKIP_TABLES]
    log.info(f"Discovered {len(tables_to_load)} tables to load.")

    failed = []

    for table in tables_to_load:
        try:
            log.info(f"  Loading: {table}")
            df = pd.read_sql(f"SELECT * FROM dbo.[{table}]", mssql)
            df.columns = [c.lower() for c in df.columns]  # lowercase for Postgres
            df.to_sql(
                table.lower(),
                pg_engine,
                schema=PG_SCHEMA,
                if_exists="replace",
                index=False,
                chunksize=5000,
            )
            log.info(f"  Done: {table} — {len(df):,} rows")
        except Exception as e:
            log.warning(f"  SKIPPED: {table} — {e}")
            failed.append(table)

    mssql.close()

    if failed:
        log.warning(f"Completed with skipped tables: {failed}")
    else:
        log.info("All tables loaded successfully.")


def save_backup():
    """Overwrite the .bak file with the current DB state so tomorrow's restore includes today's synthetic data."""
    backup_path = Path(BACKUP_FILE)
    backup_path.parent.mkdir(parents=True, exist_ok=True)

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
    parser = argparse.ArgumentParser(description="Extract SQL Server → Postgres")
    parser.add_argument(
        "date",
        nargs="?",            # אופציונלי
        default=None,
        help="Target date for synthetic invoices in YYYY-MM-DD format (e.g. 2026-03-21). "
             "If omitted, uses MAX(Recordingdate)+1 from the database.",
    )
    args = parser.parse_args()
    extract_and_load(date_override=args.date)
    save_backup()
