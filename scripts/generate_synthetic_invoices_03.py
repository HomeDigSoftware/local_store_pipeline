# ✅ IN DATA PIPE_LINE 10-06-26  (called by 02_extract_load_03.py on every pipeline run)
"""
Generate synthetic retail invoices directly in SQL Server source tables used by the dbt pipeline.

Extends generate_synthetic_invoices.py with INVENTORY REPLENISHMENT:
  When --replenish-inventory is passed the script first runs a "delivery" step that
  tops up dbo.Inventory balances before generating any invoices.  This prevents the
  item pool from running dry during long backfill runs.

  Replenishment logic (SQL-centric):
    1. Aggregate all positive (sale) line quantities sold in the last
       --replenish-window-days days from dbo.DocumentLines / dbo.Documents.
    2. For every tracked inventory row (Card_ID=11, CardsGroup=3) add back:
         max(qty_sold * --restock-multiplier, --min-restock-qty)
       Items with no sales in the window still receive --min-restock-qty units so
       slow-moving or zero-stock items are never permanently excluded from
       future invoice generation.

  The RecordingDate column in dbo.Documents is VARCHAR(8) YYYYMMDD.  String
  comparisons on YYYYMMDD are lexicographically equivalent to chronological order,
  so the window filter is index-friendly without any CAST on the indexed column.

This script inserts aligned rows into:
- dbo.Documents
- dbo.DocumentLines
- dbo.ReceiptLines

Optional inventory sell-through updates are applied to dbo.Inventory when
--update-inventory is also supplied.

Default behavior is a dry run. Use --commit to persist changes.

Example:
    python .\\scripts\\generate_synthetic_invoices_03.py \\
        --date 2026-03-21 --invoice-count 105 \\
        --replenish-inventory --replenish-window-days 7 --restock-multiplier 1.1 \\
        --seed 42 --commit
"""

from __future__ import annotations

import argparse
import math
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
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

TWOPLACES  = Decimal("0.01")
THREEPLACES = Decimal("0.001")

# ── Surprise-event window constants ────────────────────────────────────────────
# A single "surprise" day fires once per SURPRISE_WINDOW_MIN–SURPRISE_WINDOW_MAX
# days, chosen deterministically per window via random.Random(window_number).
# The day is unpredictable but fully reproducible across backfill runs.
SURPRISE_ANCHOR     = date(2021, 3, 26)   # same as pipeline anchor
SURPRISE_WINDOW_MIN = 21                   # minimum window length in days
SURPRISE_WINDOW_MAX = 28                   # maximum window length in days
# ───────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ItemRecord:
    item_id: str
    item_name: str
    sale_price: Decimal
    inventory_balance: Decimal
    popularity_weight: float


@dataclass(frozen=True)
class DayDemandProfile:
    name: str
    invoice_multiplier: float
    credit_rate_multiplier: float
    return_rate_multiplier: float
    discount_rate_multiplier: float
    hourly_windows: tuple[tuple[int, int, float], ...]


WEEKDAY_PROFILES: dict[int, DayDemandProfile] = {
    # Store hours: 05:00–23:59 every day.
    # hourly_windows: (start_hour_inclusive, end_hour_inclusive, weight).
    # Weights within each profile must sum to 1.0.
    0: DayDemandProfile(
        name="monday",
        invoice_multiplier=0.92,
        credit_rate_multiplier=0.95,
        return_rate_multiplier=1.00,
        discount_rate_multiplier=0.95,
        hourly_windows=(
            (5, 6, 0.03), (7, 9, 0.11), (9, 12, 0.26),
            (12, 15, 0.24), (15, 18, 0.19), (18, 21, 0.12), (21, 23, 0.05),
        ),
    ),
    1: DayDemandProfile(
        name="tuesday",
        invoice_multiplier=0.98,
        credit_rate_multiplier=0.98,
        return_rate_multiplier=1.00,
        discount_rate_multiplier=0.98,
        hourly_windows=(
            (5, 6, 0.03), (7, 9, 0.10), (9, 12, 0.25),
            (12, 15, 0.25), (15, 18, 0.20), (18, 21, 0.12), (21, 23, 0.05),
        ),
    ),
    2: DayDemandProfile(
        name="wednesday",
        invoice_multiplier=1.03,
        credit_rate_multiplier=1.00,
        return_rate_multiplier=1.00,
        discount_rate_multiplier=1.00,
        hourly_windows=(
            (5, 6, 0.03), (7, 9, 0.09), (9, 12, 0.24),
            (12, 15, 0.26), (15, 18, 0.21), (18, 21, 0.12), (21, 23, 0.05),
        ),
    ),
    3: DayDemandProfile(
        name="thursday",
        invoice_multiplier=1.10,
        credit_rate_multiplier=1.08,
        return_rate_multiplier=1.05,
        discount_rate_multiplier=1.02,
        hourly_windows=(
            (5, 6, 0.03), (7, 9, 0.08), (9, 12, 0.21),
            (12, 15, 0.25), (15, 18, 0.23), (18, 22, 0.14), (22, 23, 0.06),
        ),
    ),
    4: DayDemandProfile(
        # Friday: ~60 % of average weekday volume.
        # Traffic pattern:
        #   05:00–06:00  store opens, very quiet
        #   06:00–13:00  heavy morning peak
        #   13:00–17:00  drops (quiet afternoon)
        #   17:00–19:00  evening spike (~2× the morning per-hour rate)
        #   19:00–22:00  falls again
        #   22:00–23:59  late-night rise toward close
        name="friday",
        invoice_multiplier=0.60,
        credit_rate_multiplier=1.05,
        return_rate_multiplier=0.95,
        discount_rate_multiplier=1.05,
        hourly_windows=(
            (5,  5,  0.02),
            (6,  12, 0.40),
            (13, 16, 0.09),
            (17, 18, 0.24),
            (19, 21, 0.13),
            (22, 23, 0.12),
        ),
    ),
    5: DayDemandProfile(
        # Saturday: ~60 % of average weekday volume.
        # Traffic pattern:
        #   05:00–11:00  quiet morning
        #   11:00–15:00  traffic rises
        #   15:00–19:00  quiet again
        #   19:00–23:59  steady rise through evening until close
        name="saturday",
        invoice_multiplier=0.60,
        credit_rate_multiplier=1.05,
        return_rate_multiplier=0.90,
        discount_rate_multiplier=1.10,
        hourly_windows=(
            (5,  10, 0.10),
            (11, 14, 0.27),
            (15, 18, 0.13),
            (19, 23, 0.50),
        ),
    ),
    6: DayDemandProfile(
        name="sunday",
        invoice_multiplier=1.15,
        credit_rate_multiplier=1.02,
        return_rate_multiplier=1.08,
        discount_rate_multiplier=1.04,
        hourly_windows=(
            (5, 6, 0.03), (7, 9, 0.13), (9, 12, 0.25),
            (12, 15, 0.22), (15, 18, 0.20), (18, 21, 0.12), (21, 23, 0.05),
        ),
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate synthetic invoices for the POS source tables (v03 — with replenishment)."
    )
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Business date for generated invoices in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--invoice-count",
        type=int,
        default=30,
        help="Number of invoices to generate.",
    )
    parser.add_argument(
        "--min-lines",
        type=int,
        default=1,
        help="Minimum number of lines per invoice.",
    )
    parser.add_argument(
        "--max-lines",
        type=int,
        default=5,
        help="Maximum number of lines per invoice.",
    )
    parser.add_argument(
        "--credit-rate",
        type=float,
        default=0.20,
        help="Probability that an invoice uses payment type 3 (credit).",
    )
    parser.add_argument(
        "--return-rate",
        type=float,
        default=0.03,
        help="Probability that a generated invoice is a return with negative totals.",
    )
    parser.add_argument(
        "--discount-rate",
        type=float,
        default=0.15,
        help="Probability that a line receives a small random discount.",
    )
    parser.add_argument(
        "--update-inventory",
        action="store_true",
        help="Apply sell-through inventory balance updates in dbo.Inventory.",
    )

    # ── Replenishment arguments (new in v03) ───────────────────────────────────
    parser.add_argument(
        "--replenish-inventory",
        action="store_true",
        help=(
            "Run a 'delivery' step before invoice generation: restock dbo.Inventory "
            "based on quantities sold in the look-back window."
        ),
    )
    parser.add_argument(
        "--replenish-window-days",
        type=int,
        default=7,
        help=(
            "Number of days to look back when calculating how much was sold "
            "for the replenishment calculation. Default: 7."
        ),
    )
    parser.add_argument(
        "--restock-multiplier",
        type=float,
        default=1.1,
        help=(
            "Restock factor applied to qty_sold: restock = qty_sold * multiplier. "
            "A value > 1.0 means the owner orders slightly more than was sold. "
            "Default: 1.1 (matches RESTOCK_MULTIPLIER in 02_extract_load_03.py, the "
            "value the pipeline always passes explicitly)."
        ),
    )
    parser.add_argument(
        "--min-restock-qty",
        type=float,
        default=10.0,
        help=(
            "Minimum units to add per item even if nothing was sold in the window. "
            "Prevents permanently zero-stock items. Default: 10.0."
        ),
    )
    # ──────────────────────────────────────────────────────────────────────────

    parser.add_argument(
        "--trend-anchor",
        default=None,
        metavar="YYYY-MM-DD",
        help=(
            "Start date for compound-growth trend.  "
            "If omitted, no trend is applied."
        ),
    )
    parser.add_argument(
        "--trend-rate",
        type=float,
        default=0.0,
        help=(
            "Daily compound growth rate applied to the invoice count.  "
            "Example: 0.0003 ≈ +11%% per year.  Default: 0.0 (no trend)."
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help=(
            "Random seed for reproducible output.  "
            "If omitted, a per-date seed is derived from --date (YYYYMMDD as int), "
            "so every calendar day gets a unique but deterministic RNG sequence."
        ),
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Persist inserts. Without this flag the script rolls back.",
    )
    args = parser.parse_args()

    if args.invoice_count <= 0:
        parser.error("--invoice-count must be positive.")
    if args.min_lines <= 0:
        parser.error("--min-lines must be positive.")
    if args.max_lines < args.min_lines:
        parser.error("--max-lines must be greater than or equal to --min-lines.")
    for flag_name in ("credit_rate", "return_rate", "discount_rate"):
        value = getattr(args, flag_name)
        if not 0 <= value <= 1:
            parser.error(f"--{flag_name.replace('_', '-')} must be between 0 and 1.")
    if args.replenish_window_days <= 0:
        parser.error("--replenish-window-days must be positive.")
    if args.restock_multiplier <= 0:
        parser.error("--restock-multiplier must be positive.")
    if args.min_restock_qty < 0:
        parser.error("--min-restock-qty must be non-negative.")

    datetime.strptime(args.date, "%Y-%m-%d")
    return args


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def quantize_qty(value: Decimal) -> Decimal:
    return value.quantize(THREEPLACES, rounding=ROUND_HALF_UP)


def to_source_date(target_date: date) -> str:
    return target_date.strftime("%Y%m%d")


def resolve_day_profile(target_date: date) -> DayDemandProfile:
    return WEEKDAY_PROFILES[target_date.weekday()]


def adjusted_rate(base_rate: float, multiplier: float) -> float:
    return max(0.0, min(1.0, base_rate * multiplier))


def _monthly_event_multiplier(target_date: date, rng: random.Random) -> float:
    """Israeli payroll calendar: payday is the 10th of every month.

    - Days  4-9 : pre-payday slump  — money running out before the 10th
    - Days 10-12: post-payday boost  — salary just arrived
    - All other days: no adjustment
    """
    d = target_date.day
    if 4 <= d <= 9:
        return rng.uniform(0.62, 0.82)
    if 10 <= d <= 12:
        return rng.uniform(1.10, 1.30)
    return 1.0


def _surprise_event_multiplier(target_date: date) -> float:
    """Fire a strong or weak surprise day once every 3-4 weeks.

    Time since SURPRISE_ANCHOR is divided into variable-length windows
    (SURPRISE_WINDOW_MIN–SURPRISE_WINDOW_MAX days).  Each window has
    exactly one surprise day, chosen via random.Random(window_number)
    so the day is unpredictable but deterministic across runs.
    """
    days_from_anchor = (target_date - SURPRISE_ANCHOR).days
    if days_from_anchor < 0:
        return 1.0

    window_start = 0
    window_num   = 0
    while True:
        w_rng  = random.Random(window_num)
        w_size = w_rng.randint(SURPRISE_WINDOW_MIN, SURPRISE_WINDOW_MAX)
        w_end  = window_start + w_size - 1
        if window_start <= days_from_anchor <= w_end:
            surprise_offset = w_rng.randint(0, w_size - 1)
            if days_from_anchor == window_start + surprise_offset:
                is_strong = w_rng.random() < 0.60
                if is_strong:
                    return w_rng.uniform(1.35, 1.65)
                else:
                    return w_rng.uniform(0.30, 0.52)
            return 1.0
        window_start = w_end + 1
        window_num  += 1


def adjusted_invoice_count(
    base_invoice_count: int,
    target_date: date,
    rng: random.Random,
    trend_anchor: date | None = None,
    trend_rate: float = 0.0,
) -> int:
    """Compute invoice count using 4 variability layers:

    1. Weekday multiplier  — Mon–Sun seasonality profile
    2. Trend factor        — compound growth: (1 + rate) ** days_since_anchor
    3. Lognormal jitter    — sigma=0.20 gives typical ±22% daily swing
    4. Event multiplier    — priority: surprise day > monthly calendar event
    """
    profile = resolve_day_profile(target_date)

    # Layer 1: weekday
    weekday_mult = profile.invoice_multiplier

    # Layer 2: compound-growth trend
    trend_factor = 1.0
    if trend_anchor is not None and trend_rate > 0.0:
        days_elapsed = (target_date - trend_anchor).days
        if days_elapsed > 0:
            trend_factor = (1.0 + trend_rate) ** days_elapsed

    # Layer 3: lognormal jitter — more visible day-to-day swings than uniform
    jitter = math.exp(rng.gauss(0.0, 0.20))

    # Layer 4: event multiplier (surprise overrides monthly calendar)
    surprise_mult = _surprise_event_multiplier(target_date)
    event_mult    = surprise_mult if surprise_mult != 1.0 else _monthly_event_multiplier(target_date, rng)

    count = base_invoice_count * weekday_mult * trend_factor * jitter * event_mult
    return min(max(1, round(count)), 260)


def fetchone_dict(cursor: pyodbc.Cursor, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any]:
    cursor.execute(query, params)
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError(f"Query returned no rows: {query}")
    columns = [column[0] for column in cursor.description]
    return dict(zip(columns, row))


def fetchall_dicts(cursor: pyodbc.Cursor, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cursor.execute(query, params)
    rows = cursor.fetchall()
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in rows]


def fetch_template_row(cursor: pyodbc.Cursor, table_name: str, where_clause: str = "") -> dict[str, Any]:
    query = f"SELECT TOP 1 * FROM dbo.[{table_name}]"
    if where_clause:
        query += f" WHERE {where_clause}"
    query += " ORDER BY 1 DESC"
    return fetchone_dict(cursor, query)


def build_item_pool(cursor: pyodbc.Cursor) -> list[ItemRecord]:
    query = """
    WITH sales_history AS (
        SELECT
            dl.Item_ID,
            COUNT(*) AS line_count
        FROM dbo.DocumentLines AS dl
        GROUP BY dl.Item_ID
    )
    SELECT
        i.Item_ID,
        i.ItemDesc,
        CAST(i.Price1 AS decimal(18, 2)) AS sale_price,
        CAST(inv.InventoryBalance AS decimal(18, 3)) AS inventory_balance,
        COALESCE(sh.line_count, 1) AS line_count
    FROM dbo.Items AS i
    INNER JOIN dbo.Inventory AS inv
        ON i.Item_ID = inv.Item_ID
    LEFT JOIN sales_history AS sh
        ON i.Item_ID = sh.Item_ID
    WHERE inv.Card_ID = 11
      AND inv.CardsGroup = 3
      AND COALESCE(inv.InventoryBalance, 0) > 0
      AND COALESCE(i.Price1, 0) > 0
      AND i.Item_ID IS NOT NULL
      AND i.ItemDesc IS NOT NULL
    """
    rows = fetchall_dicts(cursor, query)
    if not rows:
        raise RuntimeError("No eligible items were found for synthetic invoice generation.")

    pool: list[ItemRecord] = []
    for row in rows:
        sale_price = quantize_money(Decimal(str(row["sale_price"])))
        inventory_balance = quantize_qty(Decimal(str(row["inventory_balance"])))
        historical_weight = float(row["line_count"])
        inventory_weight = min(float(inventory_balance), 25.0) / 25.0
        popularity_weight = max(0.1, historical_weight * (1.0 + inventory_weight))
        pool.append(
            ItemRecord(
                item_id=str(row["Item_ID"]).strip(),
                item_name=str(row["ItemDesc"]).strip(),
                sale_price=sale_price,
                inventory_balance=inventory_balance,
                popularity_weight=popularity_weight,
            )
        )
    return pool


def replenish_inventory(
    cursor: pyodbc.Cursor,
    target_date: date,
    window_days: int,
    restock_multiplier: float,
    min_restock_qty: float,
) -> None:
    """
    Simulate a merchandise delivery by restocking dbo.Inventory.

    For every item tracked (Card_ID=11, CardsGroup=3):
      - Calculate total units SOLD (positive ItemsQty) in the last
        `window_days` days ending on `target_date` (exclusive of today —
        we restock before generating today's invoices).
      - Add back:  max(qty_sold * restock_multiplier, min_restock_qty).

    The RecordingDate column in dbo.Documents is VARCHAR(8) YYYYMMDD.
    String comparisons on YYYYMMDD are lexicographically equivalent to
    chronological order, so the WHERE clause is index-friendly without
    wrapping the indexed column in a CAST.

    The UPDATE is committed as part of the outer transaction (same connection),
    so if --commit is not passed the entire run — including the restock — rolls
    back cleanly.
    """
    # Window expressed as YYYYMMDD strings for direct VARCHAR comparison.
    window_end   = (target_date - timedelta(days=1)).strftime("%Y%m%d")   # yesterday
    window_start = (target_date - timedelta(days=window_days)).strftime("%Y%m%d")

    # ── Step 1: aggregate positive (sale) line quantities per item ─────────
    #
    # Only DocumentType=1 (regular sales invoices).
    # ItemsQty is stored as a numeric-like type; CAST guards against varchar cols.
    sales_sql = """
        SELECT
            dl.Item_ID,
            SUM(CAST(dl.ItemsQty AS DECIMAL(18, 3))) AS qty_sold
        FROM dbo.DocumentLines AS dl
        INNER JOIN dbo.Documents AS d
            ON  d.Document_ID  = dl.Document_ID
            AND d.DocumentType = 1
        WHERE d.RecordingDate >= ?
          AND d.RecordingDate <= ?
          AND CAST(dl.ItemsQty AS DECIMAL(18, 3)) > 0
        GROUP BY dl.Item_ID
    """
    sales_rows = fetchall_dicts(cursor, sales_sql, (window_start, window_end))
    sales_by_item: dict[str, float] = {
        str(r["Item_ID"]).strip(): float(r["qty_sold"])
        for r in sales_rows
    }

    # ── Step 2: fetch all tracked inventory items with current balance ────────
    inv_rows = fetchall_dicts(
        cursor,
        """
        SELECT Item_ID,
               CAST(COALESCE(InventoryBalance, 0) AS DECIMAL(18, 3)) AS current_balance
        FROM   dbo.Inventory
        WHERE  Card_ID = 11 AND CardsGroup = 3
        """,
    )

    total_items       = len(inv_rows)
    items_restocked   = 0
    items_skipped     = 0
    total_units_added = Decimal("0.000")

    # ── Step 3: restock only items where current inventory < 7-day sales ──────
    #
    # Condition: current_balance < qty_sold_in_window
    # Restock amount: qty_sold * restock_multiplier (sold + 10%)
    # Items with sufficient stock or zero sales are skipped entirely.
    for row in inv_rows:
        item_id         = str(row["Item_ID"]).strip()
        current_balance = float(row["current_balance"])
        qty_sold        = sales_by_item.get(item_id, 0.0)

        if current_balance >= qty_sold:
            items_skipped += 1
            continue

        restock         = qty_sold * restock_multiplier
        restock_decimal = quantize_qty(Decimal(str(round(restock, 3))))

        if restock_decimal <= 0:
            items_skipped += 1
            continue

        cursor.execute(
            """
            UPDATE dbo.Inventory
            SET    InventoryBalance = CAST(
                       COALESCE(InventoryBalance, 0) + ?
                   AS NUMERIC(18, 3))
            WHERE  Item_ID    = ?
              AND  Card_ID    = 11
              AND  CardsGroup = 3
            """,
            float(restock_decimal),
            item_id,
        )

        total_units_added += restock_decimal
        items_restocked   += 1

    print(
        f"Replenishment | window: {window_start}–{window_end} "
        f"({window_days} days) | "
        f"{total_items} items evaluated: "
        f"{items_restocked} restocked (inventory < 7d sales) + "
        f"{items_skipped} skipped (sufficient stock or no sales) | "
        f"total units added: {total_units_added}"
    )


def choose_sale_time_seconds(rng: random.Random, profile: DayDemandProfile) -> int:
    weights = [window[2] for window in profile.hourly_windows]
    start_hour, end_hour, _ = rng.choices(profile.hourly_windows, weights=weights, k=1)[0]
    hour   = rng.randint(start_hour, end_hour)
    minute = rng.randint(0, 59)
    second = rng.randint(0, 59)
    return hour * 3600 + minute * 60 + second


def choose_line_count(rng: random.Random, min_lines: int, max_lines: int) -> int:
    line_options = list(range(min_lines, max_lines + 1))
    weights = [1 / line_count for line_count in line_options]
    return rng.choices(line_options, weights=weights, k=1)[0]


def choose_quantity(rng: random.Random, available_inventory: Decimal) -> Decimal:
    qty_options = [Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4")]
    weights = [0.72, 0.18, 0.07, 0.03]
    quantity = rng.choices(qty_options, weights=weights, k=1)[0]
    if available_inventory < quantity:
        quantity = max(Decimal("1"), available_inventory)
    return quantize_qty(quantity)


def choose_items(
    rng: random.Random,
    item_pool: list[ItemRecord],
    requested_lines: int,
    inventory_tracker: dict[str, Decimal],
) -> list[ItemRecord]:
    available_items = [
        item for item in item_pool if inventory_tracker[item.item_id] >= Decimal("1")
    ]
    if not available_items:
        raise RuntimeError("No items with available inventory remain for generation.")

    chosen: list[ItemRecord] = []
    seen_ids: set[str] = set()
    max_pick_count = min(requested_lines, len(available_items))
    while len(chosen) < max_pick_count:
        candidates = [item for item in available_items if item.item_id not in seen_ids]
        if not candidates:
            break
        weights = [item.popularity_weight for item in candidates]
        item = rng.choices(candidates, weights=weights, k=1)[0]
        chosen.append(item)
        seen_ids.add(item.item_id)
    return chosen


def next_identity_values(cursor: pyodbc.Cursor) -> dict[str, int]:
    values = {}
    lookups = {
        "document_id": "SELECT ISNULL(MAX(Document_ID), 0) + 1 AS next_value FROM dbo.Documents",
    }
    for key, query in lookups.items():
        values[key] = int(fetchone_dict(cursor, query)["next_value"])
    return values


def build_insert_sql(table_name: str, column_names: list[str]) -> str:
    columns_sql  = ", ".join(f"[{column_name}]" for column_name in column_names)
    placeholders = ", ".join("?" for _ in column_names)
    return f"INSERT INTO dbo.[{table_name}] ({columns_sql}) VALUES ({placeholders})"


def insert_row(cursor: pyodbc.Cursor, table_name: str, row_values: dict[str, Any]) -> None:
    identity_columns = {
        "Documents":     {"s__sequence"},
        "DocumentLines": {"s__sequence"},
        "ReceiptLines":  {"s__sequence"},
    }
    column_names = [
        column_name
        for column_name in row_values.keys()
        if column_name not in identity_columns.get(table_name, set())
    ]
    sql = build_insert_sql(table_name, column_names)
    cursor.execute(sql, tuple(row_values[column_name] for column_name in column_names))


def update_inventory_row(
    cursor: pyodbc.Cursor,
    item_id: str,
    quantity_delta: Decimal,
) -> None:
    cursor.execute(
        """
        UPDATE dbo.Inventory
        SET InventoryBalance = CAST(COALESCE(InventoryBalance, 0) + ? AS numeric(18, 3))
        WHERE Item_ID   = ?
          AND Card_ID   = 11
          AND CardsGroup = 3
        """,
        float(quantity_delta),
        item_id,
    )


def main() -> None:
    args = parse_args()

    target_date = datetime.strptime(args.date, "%Y-%m-%d").date()

    # Use a per-date seed when none is supplied so every calendar day gets a
    # unique RNG sequence (fixes the flat-graph problem caused by a fixed seed).
    seed = args.seed if args.seed is not None else int(target_date.strftime("%Y%m%d"))
    rng  = random.Random(seed)

    trend_anchor = (
        datetime.strptime(args.trend_anchor, "%Y-%m-%d").date()
        if args.trend_anchor
        else None
    )

    source_date  = to_source_date(target_date)
    day_profile  = resolve_day_profile(target_date)
    planned_invoice_count = adjusted_invoice_count(
        args.invoice_count,
        target_date,
        rng,
        trend_anchor=trend_anchor,
        trend_rate=args.trend_rate,
    )
    credit_rate   = adjusted_rate(args.credit_rate,   day_profile.credit_rate_multiplier)
    return_rate   = adjusted_rate(args.return_rate,   day_profile.return_rate_multiplier)
    discount_rate = adjusted_rate(args.discount_rate, day_profile.discount_rate_multiplier)

    connection = pyodbc.connect(MSSQL_CONN_STR)
    connection.autocommit = False
    cursor = connection.cursor()

    # ── Inventory replenishment (NEW in v03) ───────────────────────────────
    # Run BEFORE build_item_pool() so the freshly restocked balances are
    # visible to the item pool query and the in-memory inventory tracker.
    if args.replenish_inventory:
        replenish_inventory(
            cursor,
            target_date,
            window_days=args.replenish_window_days,
            restock_multiplier=args.restock_multiplier,
            min_restock_qty=args.min_restock_qty,
        )

    item_pool = build_item_pool(cursor)
    inventory_tracker = {
        item.item_id: item.inventory_balance for item in item_pool
    }

    document_template      = fetch_template_row(cursor, "Documents")
    document_line_template = fetch_template_row(cursor, "DocumentLines")
    receipt_template       = fetch_template_row(cursor, "ReceiptLines", "PaymentType IN (1, 3)")
    identity_values        = next_identity_values(cursor)

    credit_card_types = [
        row["CreditCardType"]
        for row in fetchall_dicts(
            cursor,
            "SELECT CreditCardType FROM dbo.CreditCardsTypes WHERE CreditCardType IS NOT NULL",
        )
    ]
    if not credit_card_types:
        credit_card_types = ["8"]

    generated_documents = 0
    generated_lines     = 0
    payment_type_counts: defaultdict[int, int] = defaultdict(int)
    return_documents    = 0
    total_revenue       = Decimal("0.00")

    try:
        for _ in range(planned_invoice_count):
            document_id = identity_values["document_id"]
            identity_values["document_id"] += 1

            is_return  = rng.random() < return_rate
            if is_return:
                return_documents += 1

            line_count   = choose_line_count(rng, args.min_lines, args.max_lines)
            chosen_items = choose_items(rng, item_pool, line_count, inventory_tracker)

            document_total = Decimal("0.00")
            print_time     = choose_sale_time_seconds(rng, day_profile)
            line_rows: list[dict[str, Any]] = []

            for line_number, item in enumerate(chosen_items, start=1):
                available_inventory = inventory_tracker[item.item_id]
                quantity = choose_quantity(rng, available_inventory)
                if quantity <= 0:
                    continue

                base_unit_price = item.sale_price
                if rng.random() < discount_rate:
                    discount_factor = Decimal(str(rng.uniform(0.85, 0.98)))
                    base_unit_price = quantize_money(item.sale_price * discount_factor)

                line_total    = quantize_money(base_unit_price * quantity)
                signed_quantity = -quantity if is_return else quantity
                signed_total    = -line_total if is_return else line_total
                document_total += signed_total

                inventory_tracker[item.item_id] = quantize_qty(
                    inventory_tracker[item.item_id] + quantity
                    if is_return
                    else inventory_tracker[item.item_id] - quantity
                )

                line_row = dict(document_line_template)
                line_row["DocumentType"]           = 1
                line_row["Document_ID"]            = document_id
                line_row["Line_ID"]                = line_number
                line_row["DateSetting"]            = source_date
                line_row["Item_ID"]                = item.item_id
                line_row["Details"]                = item.item_name[:50]
                line_row["UnitPriceVATincluded"]   = float(base_unit_price)
                line_row["ItemsQty"]               = float(signed_quantity)
                line_row["LineDiscount"]           = 0
                line_row["TotalPerLine_IncVAT"]    = float(signed_total)
                line_rows.append(line_row)

                if args.update_inventory:
                    inventory_delta = quantity if is_return else -quantity
                    update_inventory_row(cursor, item.item_id, inventory_delta)

            if not line_rows:
                continue

            document_row = dict(document_template)
            document_row["DocumentType"]                     = 1
            document_row["Document_ID"]                      = document_id
            document_row["RecordingDate"]                    = source_date
            document_row["PrintTime"]                        = print_time
            document_row["ReferenceDate"]                    = source_date
            document_row["ValueDate"]                        = source_date
            document_row["GeneralTotalIncludeVAT"]           = float(quantize_money(document_total))
            document_row["TotalBeforeDiscountAndNoVAT"]      = float(quantize_money(document_total))
            if "TotalBeforeDiscountAndNoTAX" in document_row:
                document_row["TotalBeforeDiscountAndNoTAX"]  = float(quantize_money(document_total))
            document_row["Total_NoVAT"]                      = float(quantize_money(document_total))
            document_row["VAT"]                              = 0
            document_row["TotalItems"]                       = float(sum(abs(row["ItemsQty"]) for row in line_rows))
            document_row["LastLine"]                         = len(line_rows)
            document_row["Details"]                          = "synthetic_invoice"
            document_row["IsPrinted"]                        = 1
            document_row["TransmittedToCenter"]              = 0

            payment_type = 3 if rng.random() < credit_rate else 1
            payment_type_counts[payment_type] += 1
            receipt_row = dict(receipt_template)
            receipt_row["Receipt_ID"]                       = document_id
            receipt_row["PaymentType"]                      = payment_type
            receipt_row["RecordingDate"]                    = source_date
            receipt_row["PaymentDate"]                      = source_date
            receipt_row["SystemCurrencyAmount"]             = float(quantize_money(document_total))
            receipt_row["AccountNumber_moreInfo"]           = "1"
            receipt_row["CreditCardType"]                   = (
                rng.choice(credit_card_types)
                if payment_type == 3
                else receipt_template.get("CreditCardType") or credit_card_types[0]
            )
            receipt_row["NumberOfPayments"]                 = 1
            receipt_row["FirstPayment_Total"]               = float(quantize_money(document_total))
            receipt_row["OtherPayments_currencyRange"]      = 0
            receipt_row["TransmittedToCenter"]              = 0

            insert_row(cursor, "Documents",     document_row)
            for line_row in line_rows:
                insert_row(cursor, "DocumentLines", line_row)
            insert_row(cursor, "ReceiptLines",  receipt_row)

            generated_documents += 1
            generated_lines     += len(line_rows)
            total_revenue       += quantize_money(document_total)

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
    print(f"Business date: {source_date}")
    print(f"Demand profile: {day_profile.name}")
    print(f"Requested invoice count: {args.invoice_count}")
    print(f"Invoices generated: {generated_documents}")
    print(f"Line rows generated: {generated_lines}")
    print(f"Return documents: {return_documents}")
    print(f"Total gross amount: {quantize_money(total_revenue)}")
    print(f"Payment mix: {dict(sorted(payment_type_counts.items()))}")
    print("Applied constraints:")
    print("- uses only Items with positive price and active Inventory rows for Card_ID=11 and CardsGroup=3")
    print("- limits quantity by available inventory")
    print("- biases item selection toward historically sold items")
    print("- adjusts invoice volume by weekday or weekend seasonality")
    print("- uses day-specific hourly demand windows for receipt timestamps")
    print("- generates one valid ReceiptLines row per document so int_sales__line_items remains joinable")
    if args.replenish_inventory:
        print("- inventory restocked before generation (see Replenishment line above)")


if __name__ == "__main__":
    main()
