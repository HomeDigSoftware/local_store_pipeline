# NEW — economical Supabase loader. Does NOT overwrite the working 03_load_to_supabase.py.
"""
03_load_to_supabase_allowlist.py — push ONLY the source tables dbt prod actually
reads (8 tables), instead of all ~539 tables in local raw.

WHY
---
Diagnosis (SUPABASE_LOAD_REDUCTION_PLAN.md §1b) showed Supabase `raw` holds 539
tables, and the working 03 pushes ALL of them with `if_exists="replace"`
(DROP+CREATE), which (a) is heavy write IO and (b) forces PostgREST to re-introspect
539 tables on every run (the schema-reload storm).

This version fixes both:
  1. ALLOWLIST — pushes only the 8 source tables referenced by dbt models
     (verified via `source('store_data', ...)` calls).
  2. NO DDL on repeat runs — if the target table already exists it does
     TRUNCATE + append (DML only) instead of DROP+CREATE, so PostgREST does NOT
     reload its schema cache. DDL happens only on the very first load of a table.

This is a drop-in replacement for `03_load_to_supabase.py` once verified.
It does NOT touch the `store_pipeline` schema (that is built by dbt --target prod).

PREREQUISITE BEFORE CLEANUP: the Next.js dashboard must read from
`store_pipeline.rpt_*`, NOT from `raw.*`, before old raw tables are removed.
"""

import sys
import os
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import pandas as pd
import sqlalchemy as sa
from sqlalchemy import text

# ── Configuration ──────────────────────────────────────────────────────────────
LOCAL_PG_URL = (
    f"postgresql://{os.environ['PG_USER']}:{os.environ['PG_PASSWORD']}"
    f"@{os.environ['PG_HOST']}:{os.environ['PG_PORT']}/{os.environ['PG_DATABASE']}"
)
SUPABASE_URL  = os.environ["SUPABASE_URL"]
SOURCE_SCHEMA = "raw"
TARGET_SCHEMA = "raw"

# The ONLY source tables dbt prod needs (verified via source('store_data', ...) refs).
# Must match KEEP in cleanup_supabase_raw.py.
ALLOWLIST = [
    "documents",
    "documentlines",
    "receiptlines",
    "inventory",
    "items",
    "itemtypes",
    "employeesattendance",
    "employeesselection_byentrance",
]
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


def _table_exists(conn, schema: str, table: str) -> bool:
    return conn.execute(
        text(
            "select 1 from information_schema.tables "
            "where table_schema = :s and table_name = :t"
        ),
        {"s": schema, "t": table},
    ).first() is not None


def load_allowlist() -> None:
    log.info("Connecting to local Postgres and Supabase…")
    local_engine = sa.create_engine(LOCAL_PG_URL)
    supabase_engine = sa.create_engine(SUPABASE_URL)

    with supabase_engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {TARGET_SCHEMA}"))

    local_tables = set(sa.inspect(local_engine).get_table_names(schema=SOURCE_SCHEMA))

    pushed, skipped, failed = [], [], []

    for t in ALLOWLIST:
        if t not in local_tables:
            log.warning("  local %s.%s missing — skipping.", SOURCE_SCHEMA, t)
            skipped.append(t)
            continue
        try:
            df = pd.read_sql_table(t, local_engine, schema=SOURCE_SCHEMA)

            with supabase_engine.connect() as conn:
                exists = _table_exists(conn, TARGET_SCHEMA, t)

            if exists:
                # DML path — no DDL → no PostgREST schema-cache reload.
                try:
                    with supabase_engine.begin() as conn:
                        conn.execute(text(f'TRUNCATE TABLE "{TARGET_SCHEMA}"."{t}"'))
                    df.to_sql(t, supabase_engine, schema=TARGET_SCHEMA,
                              if_exists="append", index=False, chunksize=2000)
                    mode = "truncate+append"
                except Exception as drift:
                    # schema drift → fall back to recreate (one-time DDL)
                    log.warning("  %s append failed (%s) — recreating.", t, str(drift)[:80])
                    df.to_sql(t, supabase_engine, schema=TARGET_SCHEMA,
                              if_exists="replace", index=False, chunksize=2000)
                    mode = "replace(fallback)"
            else:
                # first load — create the table (one-time DDL)
                df.to_sql(t, supabase_engine, schema=TARGET_SCHEMA,
                          if_exists="replace", index=False, chunksize=2000)
                mode = "create"

            log.info("  pushed %s — %d rows [%s]", t, len(df), mode)
            pushed.append(t)
        except Exception as ex:
            log.warning("  FAILED %s — %s", t, str(ex)[:120])
            failed.append(t)

    log.info("Done. pushed=%d skipped=%d failed=%s", len(pushed), len(skipped), failed)
    local_engine.dispose()
    supabase_engine.dispose()


if __name__ == "__main__":
    load_allowlist()
