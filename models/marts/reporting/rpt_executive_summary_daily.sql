{{ config(materialized='table') }}

with daily_sales as (
	select *
	from {{ ref('rpt_daily_sales') }}
),

-- Full history (one snapshot per business day) so EVERY day's summary gets its own
-- inventory counts. The single-day fct_inventory_snapshot stamped one date only
-- (current_date rarely matched a sale_date), leaving these columns NULL on all other days.
inventory_by_day as (
	select
		snapshot_date as sale_date,
		sum(case when stock_status = 'OUT_OF_STOCK' then 1 else 0 end) as out_of_stock_count,
		sum(case when stock_status = 'STOCKOUT_RISK' then 1 else 0 end) as stockout_risk_count,
		sum(case when stock_status = 'DEAD_STOCK' then 1 else 0 end) as dead_stock_count,
		sum(case when stock_status = 'OVERSTOCK' then 1 else 0 end) as overstock_count,
		count(*) as inventory_items_count,
		avg(days_of_cover_30d) as avg_days_of_cover_30d
	from {{ ref('fct_inventory_snapshot_history') }}
	group by snapshot_date
),

executive_summary as (
	select
		daily_sales.sale_date,
		daily_sales.total_sales_amount,
		daily_sales.total_units_sold,
		daily_sales.ticket_count,
		daily_sales.avg_ticket_amount,
		inventory_by_day.out_of_stock_count,
		inventory_by_day.stockout_risk_count,
		inventory_by_day.dead_stock_count,
		inventory_by_day.overstock_count,
		inventory_by_day.inventory_items_count,
		inventory_by_day.avg_days_of_cover_30d,
		current_timestamp as dbt_loaded_at,
		'rpt_executive_summary_daily' as dbt_source_relation
	from daily_sales
	left join inventory_by_day
		on daily_sales.sale_date = inventory_by_day.sale_date
)

select *
from executive_summary