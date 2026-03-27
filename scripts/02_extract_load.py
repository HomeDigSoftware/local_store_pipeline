"""
Step 2 — Extract all source tables from SQL Server → load to local Postgres (raw schema).
Run this script via Task Scheduler after 01_restore_backup.py completes.

Install dependencies:
  uv add pyodbc pandas sqlalchemy psycopg2-binary
"""

import sys
import logging
import pyodbc
import pandas as pd
import sqlalchemy
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────────
MSSQL_CONN_STR = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    r"SERVER=DESKTOP-E7P613O\STORE_DATA;"
    "DATABASE=POS_SANDBOX;"
    "UID=tzaf;PWD=240683;"
)

PG_URL    = "postgresql://postgres:240683@localhost:5432/store_local"  # <-- update db name
PG_SCHEMA = "raw"

# Tables to skip (views or tables that don't exist in the backup)
SKIP_TABLES = {
    "vw_pos_cash_receipts",
}
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


def extract_and_load():
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


if __name__ == "__main__":
    extract_and_load()
