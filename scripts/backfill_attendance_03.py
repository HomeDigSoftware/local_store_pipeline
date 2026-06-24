# IN DATA PIPE_LINE 24-06-26  (one-shot / re-runnable workforce backfill)
"""
Backfill synthetic employee attendance across a date range, then re-extract the
two workforce source tables to Postgres `raw` so dbt picks up the new data.

This is decoupled from the invoice pipeline on purpose: 02_extract_load_03.py
regenerates invoices for a single business date, and re-running it over history
would DUPLICATE sales. This script only touches the two workforce tables:
  dbo.EmployeesAttendance, dbo.EmployeesSelection_byEntrance
and only re-extracts those two to raw (every other raw table is left untouched).

It reuses the per-date logic from generate_synthetic_attendance_03.py, so the
punches produced here are byte-for-byte identical to the daily pipeline's, and
re-running any range is idempotent (each date's prior punches are deleted first).

Usage:
    # dry-run preview (no DB writes):
    uv run python scripts/backfill_attendance_03.py --start 2025-12-22 --end 2026-06-23
    # persist + purge the 2 legacy .bak employees + re-extract to raw:
    uv run python scripts/backfill_attendance_03.py --start 2025-12-22 --end 2026-06-23 \
        --purge-legacy --commit --reextract
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import random
from datetime import date, datetime, timedelta
from pathlib import Path

import pyodbc
import pandas as pd
import sqlalchemy
from sqlalchemy.engine import URL
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# Load the generator module (reuse its roster/punch logic + constants).
_gen_path = Path(__file__).parent / "generate_synthetic_attendance_03.py"
_spec = importlib.util.spec_from_file_location("attendance_gen", _gen_path)
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

MSSQL_CONN_STR = gen.MSSQL_CONN_STR

PG_URL = (
    f"postgresql://{os.environ['PG_USER']}:{os.environ['PG_PASSWORD']}"
    f"@{os.environ['PG_HOST']}:{os.environ['PG_PORT']}/{os.environ['PG_DATABASE']}"
)
PG_SCHEMA = "raw"

WORKFORCE_TABLES = ["EmployeesAttendance", "EmployeesSelection_byEntrance"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill synthetic attendance over a date range.")
    p.add_argument("--start", required=True, help="First business date (YYYY-MM-DD).")
    p.add_argument("--end",   required=True, help="Last business date (YYYY-MM-DD), inclusive.")
    p.add_argument("--ot-share", type=float, default=0.08)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--purge-legacy", action="store_true",
                   help="Delete the static .bak employees (1, 8619) once, up front.")
    p.add_argument("--commit", action="store_true",
                   help="Persist. Without it the run is a dry run (rollback).")
    p.add_argument("--reextract", action="store_true",
                   help="After committing, re-extract the 2 workforce tables to Postgres raw.")
    return p.parse_args()


def generate_range(cursor, start: date, end: date, ot_share: float, seed: int | None) -> dict:
    """Generate punches for every date in [start, end]. Returns a small summary."""
    stats = {"dates": 0, "deleted": 0, "punches": 0, "per_emp": {e: 0 for e in gen.EMPLOYEE_IDS}}
    d = start
    while d <= end:
        iso_year, iso_week, iso_weekday = d.isocalendar()
        roster = gen.week_roster(iso_year, iso_week, seed)
        morning_emp, evening_emp = roster[iso_weekday - 1]
        punch_rng = random.Random(gen._seed(int(d.strftime("%Y%m%d")), seed))

        stats["deleted"] += gen.delete_existing_punches(cursor, d)

        rows = []
        rows += gen.shift_punches(d, morning_emp, gen.MORNING_IN_SEC, gen.MORNING_DUR_SEC, ot_share, punch_rng)
        rows += gen.shift_punches(d, evening_emp, gen.EVENING_IN_SEC, gen.EVENING_DUR_SEC, ot_share, punch_rng)
        for row in rows:
            gen.insert_row(cursor, "EmployeesAttendance", row)

        stats["dates"] += 1
        stats["punches"] += len(rows)
        stats["per_emp"][morning_emp] += 1
        stats["per_emp"][evening_emp] += 1
        d += timedelta(days=1)
    return stats


def reextract_to_raw() -> None:
    """Replace the two workforce tables in Postgres raw from SQL Server."""
    mssql_engine = sqlalchemy.create_engine(
        URL.create(
            "mssql+pyodbc",
            username=os.environ["MSSQL_USER"], password=os.environ["MSSQL_PASSWORD"],
            host=os.environ["MSSQL_SERVER"], database=os.environ["MSSQL_DATABASE"],
            query={"driver": "ODBC Driver 17 for SQL Server"},
        ),
        fast_executemany=True,
    )
    pg_engine = sqlalchemy.create_engine(PG_URL)
    for table in WORKFORCE_TABLES:
        df = pd.read_sql(sqlalchemy.text(f"SELECT * FROM dbo.[{table}]"), mssql_engine)
        df.columns = [c.lower() for c in df.columns]
        df["_pipeline_loaded_at"] = pd.Timestamp.now()
        df.to_sql(table.lower(), pg_engine, schema=PG_SCHEMA, if_exists="replace", index=False)
        print(f"  re-extracted dbo.{table} -> raw.{table.lower()}  ({len(df)} rows)")


def main() -> None:
    args = parse_args()
    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()
    if end < start:
        raise SystemExit("--end must be >= --start")

    connection = pyodbc.connect(MSSQL_CONN_STR)
    connection.autocommit = False
    cursor = connection.cursor()

    legacy = (0, 0)
    try:
        emps_inserted = gen.ensure_employees(cursor)
        if args.purge_legacy:
            legacy = gen.purge_legacy(cursor)
        stats = generate_range(cursor, start, end, args.ot_share, args.seed)

        if args.commit:
            connection.commit()
            mode = "committed"
        else:
            connection.rollback()
            mode = "dry-run rollback"
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    print(f"Mode: {mode}")
    print(f"Range: {start} -> {end}  ({stats['dates']} days)")
    print(f"Employees inserted (master): {emps_inserted}")
    if args.purge_legacy:
        print(f"Legacy purge: {legacy[0]} attendance rows, {legacy[1]} master rows")
    print(f"Existing punches deleted (idempotent): {stats['deleted']}")
    print(f"Punches generated: {stats['punches']}  (4 per day = 2 shifts x IN/OUT)")
    print(f"Shifts per employee: {stats['per_emp']}")

    if args.reextract:
        if mode != "committed":
            print("Skipping re-extract (not committed).")
        else:
            print("Re-extracting workforce tables to Postgres raw...")
            reextract_to_raw()


if __name__ == "__main__":
    main()
