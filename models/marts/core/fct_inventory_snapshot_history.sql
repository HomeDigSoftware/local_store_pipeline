-- HISTORICAL INVENTORY SNAPSHOT — accumulates alongside fct_inventory_snapshot
-- (does NOT replace it; the 3 reporting models still read the single-day snapshot).
--
-- Concept: accumulate ONE inventory snapshot per BUSINESS date (not wall-clock
-- current_date), appended incrementally. This lets the backfill loop build a real
-- historical inventory time-series (one row per item per business day) and lets
-- the future once-a-day automated job append exactly one new day each run.
--
-- ⚠️ USE ONLY VIA THE DAY-BY-DAY BACKFILL LOOP (scripts/full_auto_backfill.py).
--    The inventory/velocity figures upstream (int_inventory__stock_health) are
--    computed from the CURRENT loaded data state — current_inventory_qty comes from
--    the single-row `inventory` source (no date column), and sold_qty_7d/30d are
--    anchored to max(receipt_date). They are therefore point-in-time-correct ONLY
--    for the latest business day actually loaded. The loop loads data up to day D
--    (incl. the replenishment cycle) and THEN snapshots, so each row is genuine.
--    Running this once against fully-loaded data only yields the latest day.
--
-- snapshot_date source (in priority order):
--   1. dbt var 'snapshot_date' (passed per-iteration by scripts/full_auto_backfill.py)
--   2. fallback: max(receipt_date) in the data (the latest business date loaded)
--
-- Two guards:
--   * CONSISTENCY (always on): emit rows ONLY when the stamped snapshot_date equals
--     max(receipt_date) of the loaded data. A stale/arbitrary --vars date that does
--     not match the data yields ZERO rows (a visible no-op) instead of a MISLEADING
--     snapshot (today's numbers stamped with a past date). Safe by default.
--   * NEW-DATE (incremental only): emit rows ONLY when the business date is greater
--     than the latest snapshot_date already stored. Re-running the same day is a
--     no-op — the "only if the date differs" behaviour for the daily automated task.

{{ config(
    materialized = 'incremental',
    unique_key = ['snapshot_date', 'item_id'],
    incremental_strategy = 'delete+insert'
) }}

with stock_health as (
    select *
    from {{ ref('int_inventory__stock_health') }}
),

as_of as (
    select
        {% if var('snapshot_date', none) is not none %}
            '{{ var("snapshot_date") }}'::date
        {% else %}
            (select max(receipt_date) from {{ ref('fct_sales') }})
        {% endif %} as snapshot_date,
        (select max(receipt_date) from {{ ref('fct_sales') }}) as data_max_date
),

inventory_snapshot_fact as (
    select
        (select snapshot_date from as_of) as snapshot_date,
        sh.item_id,
        sh.item_name,
        sh.product_category_id,
        sh.product_category_name,
        sh.current_inventory_qty,
        sh.sold_qty_7d,
        sh.sold_qty_30d,
        sh.avg_daily_sales_30d,
        sh.sales_inventory_ratio_30d,
        sh.days_of_cover_30d,
        sh.velocity_band,
        sh.stock_status,
        current_timestamp as dbt_loaded_at,
        'fct_inventory_snapshot_history' as dbt_source_relation
    from stock_health sh
)

select *
from inventory_snapshot_fact
-- CONSISTENCY guard (always on): only snapshot the latest business day actually
-- loaded, so the figures can never be stamped with a date they don't describe.
where (select snapshot_date from as_of) = (select data_max_date from as_of)
{% if is_incremental() %}
-- NEW-DATE guard (incremental only): idempotent append of genuinely new days.
  and (select snapshot_date from as_of)
      > (select coalesce(max(snapshot_date), '1900-01-01'::date) from {{ this }})
{% endif %}
