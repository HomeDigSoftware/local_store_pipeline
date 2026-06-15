{{ config(materialized='table', indexes=[{'columns': ['snapshot_date'], 'unique': true}]) }}

-- Inventory-health TREND over the accumulated snapshot history.
-- Grain: one row per snapshot_date (business day). Made possible by
-- fct_inventory_snapshot_history (a per-business-day time-series) — a single-day
-- snapshot could never support this. Depth grows as the backfill loop accumulates
-- more days. Counts current per-status item populations plus rolling/WoW context.

with history as (
	select *
	from {{ ref('fct_inventory_snapshot_history') }}
),

daily_status as (
	select
		snapshot_date,
		count(*) as items_count,
		count(*) filter (where stock_status = 'OUT_OF_STOCK') as out_of_stock_count,
		count(*) filter (where stock_status = 'STOCKOUT_RISK') as stockout_risk_count,
		count(*) filter (where stock_status = 'DEAD_STOCK') as dead_stock_count,
		count(*) filter (where stock_status = 'OVERSTOCK') as overstock_count,
		count(*) filter (where stock_status = 'HEALTHY') as healthy_count,
		-- "at risk" = items that need attention now (empty or about to be)
		count(*) filter (where stock_status in ('OUT_OF_STOCK', 'STOCKOUT_RISK')) as at_risk_count,
		sum(current_inventory_qty) as total_inventory_units,
		avg(days_of_cover_30d) as avg_days_of_cover_30d
	from history
	group by snapshot_date
),

trend as (
	select
		snapshot_date,
		items_count,
		out_of_stock_count,
		stockout_risk_count,
		dead_stock_count,
		overstock_count,
		healthy_count,
		at_risk_count,
		total_inventory_units,
		avg_days_of_cover_30d,
		-- rolling 7-day average of the at-risk population (smooths daily noise)
		avg(at_risk_count) over (order by snapshot_date rows between 6 preceding and current row) as at_risk_7d_avg,
		-- week-over-week change in at-risk count (lag 7 rows = same weekday prior week,
		-- assuming a contiguous daily history; nulls until 7 days exist)
		at_risk_count - lag(at_risk_count, 7) over (order by snapshot_date) as at_risk_wow_delta,
		current_timestamp as dbt_loaded_at,
		'rpt_inventory_health_trend' as dbt_source_relation
	from daily_status
)

select *
from trend
