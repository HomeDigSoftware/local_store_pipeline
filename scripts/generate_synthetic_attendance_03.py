# IN DATA PIPE_LINE 24-06-26  (called by 02_extract_load_03.py on every pipeline run)
"""
Generate synthetic employee attendance (clock IN/OUT punches) directly in the
SQL Server source tables used by the dbt workforce pipeline.

Mirrors the contract of generate_synthetic_invoices_03.py: writes to dbo.* via
pyodbc, dry-run by default, --commit to persist, deterministic per business date.

What it produces for a given --date D
-------------------------------------
A 3-employee store roster (101 Ronen / 102 Artyom / 103 Moshe) where every day
needs exactly TWO people on the floor and ONE is off:

    morning shift  05:00 -> 15:00  (10h)
    evening shift  15:00 -> 00:00  ( 9h, crosses midnight)

The roster is rebuilt deterministically for the whole ISO week that contains D
(seeded by ISO year+week), then only D's two shifts are emitted. Re-running any
date reproduces identical punches (idempotent), so backfills are safe.

Each shift emits two rows into dbo.EmployeesAttendance: MovementType 1 (IN) and
2 (OUT), HourTime = seconds since midnight, DateSetting = 'YYYYMMDD'. The evening
OUT lands at ~00:00 on D+1 (the dbt shift-pairing handles cross-midnight).

Overtime / payroll realism
--------------------------
A normal morning (10h) already carries 2h in the x1.25 tier (hours 9-10); a normal
evening (9h) carries 1h. With probability --ot-share (~0.08) a shift runs long into
the x1.5 tier (hours 11-12), capped hard at 12h. Small clock-in/out jitter is added
for realism.

Employees are upserted into dbo.EmployeesSelection_byEntrance on first run.
--purge-legacy (with --commit) removes the two static .bak employees (1, 8619) so
the dataset is a clean 3-person store.

Default behaviour is a dry run. Use --commit to persist changes.

Example:
    python .\\scripts\\generate_synthetic_attendance_03.py --date 2026-06-24 --commit
"""

from __future__ import annotations

import argparse
import random
from datetime import date, datetime, timedelta
from typing import Any

import pyodbc
from dotenv import load_dotenv
from pathlib import Path
import os

load_dotenv(Path(__file__).parent.parent / ".env")

MSSQL_CONN_STR = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    f"SERVER={os.environ['MSSQL_SERVER']};"
    f"DATABASE={os.environ['MSSQL_DATABASE']};"
    f"UID={os.environ['MSSQL_USER']};PWD={os.environ['MSSQL_PASSWORD']};"
)

# ── Store / roster constants ────────────────────────────────────────────────────
STORE_ID = 11

# Employee master. LongName/ShortName are Hebrew (the source columns are varchar
# with a Hebrew collation; the existing .bak rows are already Hebrew). IDs were
# verified collision-free against existing EmplyeeNumbers {1, 8619}.
EMPLOYEES: dict[int, str] = {
    101: "רונן משולם",
    102: "ארטיום מנוביץ",
    103: "משה סבג",
}
EMPLOYEE_IDS = tuple(EMPLOYEES.keys())
LEGACY_EMPLOYEE_IDS = (1, 8619)   # static .bak employees purged by --purge-legacy

# Shift templates, in seconds since midnight.
MORNING_IN_SEC   = 5 * 3600        # 05:00
MORNING_DUR_SEC  = 10 * 3600       # 10h -> 15:00
EVENING_IN_SEC   = 15 * 3600       # 15:00
EVENING_DUR_SEC  = 9 * 3600        # 9h  -> 00:00 (next day)

MAX_SHIFT_SEC    = 12 * 3600       # hard cap: a shift never exceeds 12h
SECONDS_PER_DAY  = 24 * 3600

# Idempotency band. Every "shift-start" punch (morning IN 05:00, both OUT/IN around
# 15:00) sits at HourTime >= this on its DateSetting; the only cross-midnight punch
# (an evening OUT) lands at HourTime well below this on the NEXT day. 04:00 gives a
# wide margin between the latest possible cross-midnight OUT (~03:08) and the
# earliest shift-start (05:00).
MIDNIGHT_BAND_SEC = 4 * 3600       # 04:00

MOVE_IN  = 1
MOVE_OUT = 2

# Valid partitions of the 7 weekly off-days across 3 employees with each part in
# 1..3 -> each employee works 4..6 shifts/week (unequal but bounded).
OFF_DAY_PARTITIONS = (
    (1, 3, 3), (3, 1, 3), (3, 3, 1),
    (2, 2, 3), (2, 3, 2), (3, 2, 2),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate synthetic employee attendance for the POS source tables."
    )
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Business date for generated punches in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--ot-share",
        type=float,
        default=0.08,
        help="Probability that a single shift runs long into the x1.5 (11-12h) tier.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional integer offset added to the per-week / per-day seeds.",
    )
    parser.add_argument(
        "--purge-legacy",
        action="store_true",
        help="Also delete the static .bak employees (1, 8619) for a clean 3-person store.",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Persist changes. Without this flag the script is a dry run (rollback).",
    )
    return parser.parse_args()


# ── SQL helpers ─────────────────────────────────────────────────────────────────
# s__sequence is an IDENTITY column in both tables, so it is never supplied.
IDENTITY_COLUMNS: dict[str, set[str]] = {
    "EmployeesAttendance": {"s__sequence"},
    "EmployeesSelection_byEntrance": {"s__sequence"},
}


def insert_row(cursor: pyodbc.Cursor, table_name: str, row_values: dict[str, Any]) -> None:
    column_names = [
        name for name in row_values.keys()
        if name not in IDENTITY_COLUMNS.get(table_name, set())
    ]
    columns_sql  = ", ".join(f"[{name}]" for name in column_names)
    placeholders = ", ".join("?" for _ in column_names)
    sql = f"INSERT INTO dbo.[{table_name}] ({columns_sql}) VALUES ({placeholders})"
    cursor.execute(sql, tuple(row_values[name] for name in column_names))


def to_source_date(d: date) -> str:
    return d.strftime("%Y%m%d")


# ── Employee master upsert ──────────────────────────────────────────────────────
def ensure_employees(cursor: pyodbc.Cursor) -> int:
    """Insert any of the 3 store employees that are missing. Idempotent."""
    inserted = 0
    today = to_source_date(date.today())
    for emp_id, long_name in EMPLOYEES.items():
        exists = cursor.execute(
            "SELECT COUNT(*) FROM dbo.EmployeesSelection_byEntrance WHERE EmplyeeNumber = ?",
            emp_id,
        ).fetchval()
        if exists:
            continue
        insert_row(cursor, "EmployeesSelection_byEntrance", {
            "EmplyeeNumber":         emp_id,
            "ShortName":             long_name[:15],
            "LongName":              long_name[:25],
            "UpdateDate":            today,
            "ScheduledExitDate":     "00000000",
            "ScheduledExitTime":     0,
            "ExitReminderPerformed": 0,
        })
        inserted += 1
    return inserted


def purge_legacy(cursor: pyodbc.Cursor) -> tuple[int, int]:
    """Remove the static .bak employees' punches and master rows."""
    ids_sql = ", ".join("?" for _ in LEGACY_EMPLOYEE_IDS)
    att = cursor.execute(
        f"DELETE FROM dbo.EmployeesAttendance WHERE Emplyee_ID IN ({ids_sql})",
        *LEGACY_EMPLOYEE_IDS,
    ).rowcount
    sel = cursor.execute(
        f"DELETE FROM dbo.EmployeesSelection_byEntrance WHERE EmplyeeNumber IN ({ids_sql})",
        *LEGACY_EMPLOYEE_IDS,
    ).rowcount
    return att, sel


# ── Roster ──────────────────────────────────────────────────────────────────────
def _seed(base: int, offset: int | None) -> int:
    return base if offset is None else base + offset


def week_roster(iso_year: int, iso_week: int, seed_offset: int | None) -> dict[int, tuple[int, int]]:
    """
    Build the whole ISO week's roster deterministically.

    Returns {iso_weekday_index(0=Mon..6=Sun): (morning_emp_id, evening_emp_id)}.
    Each day: exactly one morning + one evening person, the third is off. No one
    works both shifts in a day. Weekly shift counts are unequal but in [4, 6].
    A light rule avoids an employee closing the evening then opening the next
    morning (only ~5h rest).
    """
    rng = random.Random(_seed(iso_year * 10000 + iso_week * 100, seed_offset))

    parts = list(rng.choice(OFF_DAY_PARTITIONS))
    emps = list(EMPLOYEE_IDS)
    rng.shuffle(emps)
    off_count = {emps[i]: parts[i] for i in range(3)}

    off_pool: list[int] = []
    for emp_id, count in off_count.items():
        off_pool.extend([emp_id] * count)
    rng.shuffle(off_pool)   # one "off" employee per day (Mon..Sun)

    roster: dict[int, tuple[int, int]] = {}
    prev_evening: int | None = None
    for day_index in range(7):
        off = off_pool[day_index]
        working = [e for e in EMPLOYEE_IDS if e != off]
        rng.shuffle(working)
        morning, evening = working[0], working[1]
        # Avoid evening(yesterday) -> morning(today) back-to-back if possible.
        if morning == prev_evening and evening != prev_evening:
            morning, evening = evening, morning
        roster[day_index] = (morning, evening)
        prev_evening = evening
    return roster


# ── Punches ─────────────────────────────────────────────────────────────────────
def shift_punches(
    business_date: date,
    emp_id: int,
    in_base_sec: int,
    base_dur_sec: int,
    ot_share: float,
    rng: random.Random,
) -> list[dict[str, Any]]:
    """Build the IN and OUT rows for one (employee, shift) on business_date."""
    in_jitter = rng.randint(-120, 480)            # -2 .. +8 min
    in_sec = in_base_sec + in_jitter

    if rng.random() < ot_share:
        # Run long into the x1.5 tier (hours 11-12), hard-capped at 12h.
        duration = rng.uniform(10.5 * 3600, 12.0 * 3600)
    else:
        # Normal day: clock out on time or up to ~7 min early. Staying *under* the
        # scheduled length keeps a 10h morning from drifting past the 10h x1.5
        # boundary on positive jitter, so the x1.5 tier stays reserved for the
        # deliberate --ot-share shifts (x1.25 is the everyday norm).
        duration = base_dur_sec - rng.randint(0, 420)
    duration = min(duration, MAX_SHIFT_SEC)

    out_abs = in_sec + duration
    in_date, out_date = business_date, business_date
    out_sec = out_abs
    if out_abs >= SECONDS_PER_DAY:
        out_date = business_date + timedelta(days=1)
        out_sec = out_abs - SECONDS_PER_DAY

    return [
        _punch_row(emp_id, in_date, int(round(in_sec)), MOVE_IN),
        _punch_row(emp_id, out_date, int(round(out_sec)), MOVE_OUT),
    ]


def _punch_row(emp_id: int, d: date, hour_sec: int, movement: int) -> dict[str, Any]:
    hour_sec = max(0, min(hour_sec, SECONDS_PER_DAY - 1))
    hh, rem = divmod(hour_sec, 3600)
    mm, ss = divmod(rem, 60)
    return {
        "StoreID":                      STORE_ID,
        "Emplyee_ID":                   emp_id,
        "DateSetting":                  to_source_date(d),
        "HourTime":                     hour_sec,
        "MovementType":                 movement,
        "TransmittedToBO":              0,
        "TransmittedToExternalSystems": 0,
        "Mark":                         " ",
        "Exceeded":                     0,
        "Reserve":                      " ",
        "FRONT_OFFICE":                 STORE_ID,
        "AttendanceRecordingType":      2,
        "UPDATE_DATETIME":              datetime(d.year, d.month, d.day, hh, mm, ss),
    }


def delete_existing_punches(cursor: pyodbc.Cursor, business_date: date) -> int:
    """
    Idempotent removal of any prior generation of business_date's shifts.

    A date's shift-start punches all sit at HourTime >= MIDNIGHT_BAND on the date
    itself; the only punch that spills to the next day is an evening OUT, at
    HourTime < MIDNIGHT_BAND. This band targets exactly those rows without
    touching the previous day's evening OUT (also on this date but < MIDNIGHT_BAND)
    or the next day's morning (>= MIDNIGHT_BAND).
    """
    ids_sql = ", ".join("?" for _ in EMPLOYEE_IDS)
    d_str = to_source_date(business_date)
    dp1_str = to_source_date(business_date + timedelta(days=1))
    return cursor.execute(
        f"""
        DELETE FROM dbo.EmployeesAttendance
        WHERE Emplyee_ID IN ({ids_sql})
          AND ( (DateSetting = ? AND HourTime >= ?)
             OR (DateSetting = ? AND HourTime <  ?) )
        """,
        *EMPLOYEE_IDS, d_str, MIDNIGHT_BAND_SEC, dp1_str, MIDNIGHT_BAND_SEC,
    ).rowcount


# ── Main ─────────────────────────────────────────────────────────────────────────
def main() -> None:
    args = parse_args()
    business_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    iso_year, iso_week, iso_weekday = business_date.isocalendar()

    roster = week_roster(iso_year, iso_week, args.seed)
    morning_emp, evening_emp = roster[iso_weekday - 1]

    punch_rng = random.Random(_seed(int(business_date.strftime("%Y%m%d")), args.seed))

    connection = pyodbc.connect(MSSQL_CONN_STR)
    connection.autocommit = False
    cursor = connection.cursor()

    legacy_att = legacy_sel = 0
    try:
        employees_inserted = ensure_employees(cursor)

        if args.purge_legacy:
            legacy_att, legacy_sel = purge_legacy(cursor)

        deleted = delete_existing_punches(cursor, business_date)

        rows: list[dict[str, Any]] = []
        rows += shift_punches(
            business_date, morning_emp, MORNING_IN_SEC, MORNING_DUR_SEC,
            args.ot_share, punch_rng,
        )
        rows += shift_punches(
            business_date, evening_emp, EVENING_IN_SEC, EVENING_DUR_SEC,
            args.ot_share, punch_rng,
        )
        for row in rows:
            insert_row(cursor, "EmployeesAttendance", row)

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

    # Summary (ASCII only — the console here is cp1252, so never print Hebrew).
    def _hhmm(sec: int) -> str:
        hh, rem = divmod(sec, 3600)
        return f"{hh:02d}:{rem // 60:02d}"

    print(f"Mode: {mode}")
    print(f"Business date: {to_source_date(business_date)} (ISO {iso_year}-W{iso_week:02d}-{iso_weekday})")
    print(f"Employees inserted (master): {employees_inserted}")
    if args.purge_legacy:
        print(f"Legacy purge: {legacy_att} attendance rows, {legacy_sel} master rows")
    print(f"Existing punches deleted (idempotent): {deleted}")
    print(f"Roster -> morning: emp {morning_emp}, evening: emp {evening_emp}, off: emp {set(EMPLOYEE_IDS) - {morning_emp, evening_emp}}")
    print("Punches generated:")
    for row in rows:
        kind = "IN " if row["MovementType"] == MOVE_IN else "OUT"
        print(f"  emp {row['Emplyee_ID']}  {row['DateSetting']}  {_hhmm(row['HourTime'])}  {kind}")


if __name__ == "__main__":
    main()
