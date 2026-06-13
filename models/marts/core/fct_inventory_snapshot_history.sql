-- EXPERIMENTAL / SANDBOX MODEL — does NOT replace fct_inventory_snapshot.sql.
--
-- Concept: accumulate ONE inventory snapshot per BUSINESS date (not wall-clock
-- current_date), appended incrementally, guarded so only a genuinely NEW
-- business date is ever added. This lets the backfill loop build a real
-- historical inventory time-series (one row per item per business day) and lets
-- the future once-a-day automated job append exactly one new day each run.
--
-- snapshot_date source (in priority order):
--   1. dbt var 'snapshot_date' (passed per-iteration by scripts/full_auto_backfill.py)
--   2. fallback: max(receipt_date) in the data (the latest business date loaded)
--
-- Guard (incremental runs only): emit rows ONLY when the resolved business date
-- is greater than the latest snapshot_date already stored. Re-running the same
-- business date is therefore a no-op — this is the "only if the date differs"
-- behaviour requested for the daily automated task.

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
        {% endif %} as snapshot_date
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

{% if is_incremental() %}
where (select snapshot_date from as_of)
      > (select coalesce(max(snapshot_date), '1900-01-01'::date) from {{ this }})
{% endif %}
