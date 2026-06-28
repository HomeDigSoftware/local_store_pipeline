# NEW — publishes ONLY the dashboard read-set to Supabase via DML (no nightly DDL).
"""
05_publish_dashboard_models.py — copy the ~20 dbt models the dashboard actually
reads from local dev (`raw`) into Supabase `store_pipeline`, using TRUNCATE+append
(DML) instead of `dbt run --target prod` (which DROP/CREATEs ~44 tables nightly).

WHY
---
Diagnosis (WORK_PLAN_2026-06-28 / README "Engineering for a free-tier warehouse"):
every DDL makes PostgREST reload its schema cache (an expensive introspection
batch incl. a pg_timezone_names scan). Rebuilding all prod models nightly triggers
that storm repeatedly on a shared free-tier CPU. This loader fixes it the same way
03_load_to_supabase_allowlist.py fixed the raw layer:
  1. ALLOWLIST — push only the read-set the dashboard queries (see
     DASHBOARD_PROD_TABLE_ALLOWLIST_2026-06-28.md, derived from the website's SQL).
  2. NO DDL on repeat runs — if the target table exists, TRUNCATE+append (DML only),
     so PostgREST does NOT reload. DDL happens only the first time a table is created;
     on that first create we also replicate the model's indexes from dev so the
     dashboard's reads stay index scans.

The full dbt DAG still builds in local dev (free/fast); only the *publish* path to
Supabase changes. The ~25 non-read-set tables (incl. the 43 MB
fct_inventory_snapshot_history) no longer need to live in prod at all — they are
dropped one-time by cleanup_supabase_store_pipeline.py (Stage 3).

USAGE
-----
  uv run python scripts/05_publish_dashboard_models.py            # dry-run (default, no writes)
  uv run python scripts/05_publish_dashboard_models.py --apply    # actually publish
  uv run python scripts/05_publish_dashboard_models.py --only dim_product --apply
"""

import sys
import os
import argparse
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
SOURCE_SCHEMA = "raw"             # dev: every dbt layer materialises into `raw`
TARGET_SCHEMA = "store_pipeline"  # prod: the schema PostgREST/the dashboard reads

# The dashboard read-set — the ONLY models that belong in prod.
# Source of truth: DASHBOARD_PROD_TABLE_ALLOWLIST_2026-06-28.md (derived from the
# website's own SQL). Must match KEEP in cleanup_supabase_store_pipeline.py.
ALLOWLIST = [
    # A. reporting tables the dashboard queries directly (14)
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
    # B. non-rpt objects the dashboard queries directly (3) — would break if dropped
    "dim_product",
    "int_sales__daily_product",
    "fct_employee_shift",
    # C. built & deployed but not yet wired in the UI (3) — keep (planned)
    "rpt_item_stockout_days",
    "rpt_sales_by_hour_weekday",
    "rpt_staffing_vs_sales_by_hour",
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


def _dev_index_defs(local_engine, table: str) -> list[str]:
    """Index DDL from dev, rewritten to target the prod schema.

    Index names are schema-scoped, so reusing dbt's generated names in
    store_pipeline is safe. Only used when a table is created for the first time;
    TRUNCATE+append preserves the indexes dbt already built in prod.
    """
    with local_engine.connect() as c:
        rows = c.execute(
            text("select indexdef from pg_indexes "
                 "where schemaname = :s and tablename = :t"),
            {"s": SOURCE_SCHEMA, "t": table},
        ).fetchall()
    defs = []
    for (indexdef,) in rows:
        # e.g. "CREATE UNIQUE INDEX <name> ON raw.<t> USING btree (...)"
        defs.append(indexdef.replace(f"ON {SOURCE_SCHEMA}.", f"ON {TARGET_SCHEMA}."))
    return defs


def publish(apply: bool, only: str | None) -> None:
    mode_banner = "APPLY (writing to Supabase)" if apply else "DRY-RUN (no writes)"
    log.info("05_publish_dashboard_models — %s", mode_banner)

    local_engine = sa.create_engine(LOCAL_PG_URL)
    supabase_engine = sa.create_engine(SUPABASE_URL)

    if apply:
        with supabase_engine.begin() as conn:
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {TARGET_SCHEMA}"))

    local_tables = set(sa.inspect(local_engine).get_table_names(schema=SOURCE_SCHEMA))
    targets = [only] if only else ALLOWLIST

    pushed, skipped, failed = [], [], []

    for t in targets:
        if t not in ALLOWLIST:
            log.warning("  %s not in ALLOWLIST — skipping.", t)
            skipped.append(t)
            continue
        if t not in local_tables:
            log.warning("  local %s.%s missing (build dev first) — skipping.", SOURCE_SCHEMA, t)
            skipped.append(t)
            continue
        try:
            with local_engine.connect() as c:
                n_rows = c.execute(text(f'select count(*) from "{SOURCE_SCHEMA}"."{t}"')).scalar()
            with supabase_engine.connect() as conn:
                exists = _table_exists(conn, TARGET_SCHEMA, t)

            plan = "truncate+append" if exists else "create+index"
            if not apply:
                extra = "" if exists else f" (+{len(_dev_index_defs(local_engine, t))} indexes)"
                log.info("  [dry-run] %-34s %7d rows  -> %s%s", t, n_rows, plan, extra)
                pushed.append(t)
                continue

            df = pd.read_sql_table(t, local_engine, schema=SOURCE_SCHEMA)

            if exists:
                # DML path — no DDL → no PostgREST schema-cache reload.
                try:
                    with supabase_engine.begin() as conn:
                        conn.execute(text(f'TRUNCATE TABLE "{TARGET_SCHEMA}"."{t}"'))
                    df.to_sql(t, supabase_engine, schema=TARGET_SCHEMA,
                              if_exists="append", index=False, chunksize=2000)
                    plan = "truncate+append"
                except Exception as drift:
                    # schema drift (model added/changed a column) → recreate this one
                    log.warning("  %s append failed (%s) — recreating + reindexing.",
                                t, str(drift)[:80])
                    df.to_sql(t, supabase_engine, schema=TARGET_SCHEMA,
                              if_exists="replace", index=False, chunksize=2000)
                    _create_indexes(supabase_engine, local_engine, t)
                    plan = "recreate(drift)"
            else:
                # first load — create the table once (DDL) + replicate indexes
                df.to_sql(t, supabase_engine, schema=TARGET_SCHEMA,
                          if_exists="replace", index=False, chunksize=2000)
                _create_indexes(supabase_engine, local_engine, t)
                plan = "create+index"

            log.info("  pushed %-34s %7d rows  [%s]", t, len(df), plan)
            pushed.append(t)
        except Exception as ex:
            log.warning("  FAILED %s — %s", t, str(ex)[:140])
            failed.append(t)

    log.info("Done (%s). ok=%d skipped=%d failed=%s",
             "apply" if apply else "dry-run", len(pushed), len(skipped), failed)
    local_engine.dispose()
    supabase_engine.dispose()


def _create_indexes(supabase_engine, local_engine, table: str) -> None:
    for ddl in _dev_index_defs(local_engine, table):
        try:
            with supabase_engine.begin() as conn:
                conn.execute(text(ddl))
        except Exception as ex:
            log.warning("    index skipped on %s — %s", table, str(ex)[:100])


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Publish the dashboard read-set to Supabase via DML.")
    ap.add_argument("--apply", action="store_true",
                    help="actually write to Supabase (default: dry-run, no writes)")
    ap.add_argument("--only", metavar="TABLE",
                    help="publish a single allowlist table (for testing)")
    args = ap.parse_args()
    publish(apply=args.apply, only=args.only)
