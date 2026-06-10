# ✅ IN DATA PIPE_LINE 10-06-26  (called by 04_backfill_loop.py after all iterations complete)
"""
Step 3 — Push all tables from local Postgres (store_local.raw) → Supabase (postgres.raw).
Run this after 02_extract_load.py, before dbt run --target prod.

Install dependencies:
  uv add sqlalchemy psycopg2-binary
"""

import sys
import logging
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import pandas as pd
import sqlalchemy

# ── Configuration ──────────────────────────────────────────────────────────────
LOCAL_PG_URL  = (
    f"postgresql://{os.environ['PG_USER']}:{os.environ['PG_PASSWORD']}"
    f"@{os.environ['PG_HOST']}:{os.environ['PG_PORT']}/{os.environ['PG_DATABASE']}"
)
SUPABASE_URL  = os.environ["SUPABASE_URL"]
SOURCE_SCHEMA = "raw"
TARGET_SCHEMA = "raw"
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


def load_to_supabase():
    log.info("Connecting to local Postgres...")
    local_engine = sqlalchemy.create_engine(LOCAL_PG_URL)

    log.info("Connecting to Supabase...")
    supabase_engine = sqlalchemy.create_engine(SUPABASE_URL)

    # Create raw schema in Supabase if it doesn't exist
    with supabase_engine.connect() as conn:
        conn.execute(sqlalchemy.text(f"CREATE SCHEMA IF NOT EXISTS {TARGET_SCHEMA}"))
        conn.commit()

    # Discover all tables in the local raw schema
    with local_engine.connect() as conn:
        result = conn.execute(sqlalchemy.text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = :schema AND table_type = 'BASE TABLE' "
            "ORDER BY table_name"
        ), {"schema": SOURCE_SCHEMA})
        tables = [row[0] for row in result]

    log.info(f"Found {len(tables)} tables to push to Supabase.")

    failed = []

    for table in tables:
        try:
            log.info(f"  Uploading: {table}")
            df = pd.read_sql_table(table, local_engine, schema=SOURCE_SCHEMA)
            df.to_sql(
                table,
                supabase_engine,
                schema=TARGET_SCHEMA,
                if_exists="replace",
                index=False,
                chunksize=2000,
            )
            log.info(f"  Done: {table} — {len(df):,} rows")
        except Exception as e:
            log.warning(f"  SKIPPED: {table} — {e}")
            failed.append(table)

    if failed:
        log.warning(f"Completed with skipped tables: {failed}")
    else:
        log.info("All tables loaded to Supabase successfully.")


if __name__ == "__main__":
    load_to_supabase()
