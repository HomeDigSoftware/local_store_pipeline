{{ config(materialized='table') }}

-- Latest business-day slice of the historical inventory snapshot.
-- Replaces the old current_date-stamped build: snapshot_date is now the most recent
-- BUSINESS day accumulated by fct_inventory_snapshot_history, so the "current view"
-- reports (rpt_inventory_risk, rpt_product_velocity) read a real, dated slice instead
-- of a wall-clock stamp that never matched the sales calendar. Those two models are
-- unchanged — they still ref this model; only its source moved to the history table.
with history as (
	select *
	from {{ ref('fct_inventory_snapshot_history') }}
),

latest as (
	select *
	from history
	where snapshot_date = (select max(snapshot_date) from history)
)

select
	snapshot_date,
	item_id,
	item_name,
	product_category_id,
	product_category_name,
	current_inventory_qty,
	sold_qty_7d,
	sold_qty_30d,
	avg_daily_sales_30d,
	sales_inventory_ratio_30d,
	days_of_cover_30d,
	velocity_band,
	stock_status,
	current_timestamp as dbt_loaded_at,
	'fct_inventory_snapshot' as dbt_source_relation
from latest
