{{ config(materialized='table') }}

with inventory_snapshot as (
	select *
	from {{ ref('fct_inventory_snapshot') }}
),

inventory_risk_report as (
	select
		snapshot_date,
		item_id,
		item_name,
		product_category_id,
		product_category_name,
		current_inventory_qty,
		sold_qty_30d,
		days_of_cover_30d,
		velocity_band,
		stock_status
	from inventory_snapshot
	where stock_status <> 'HEALTHY'
)

select *
from inventory_risk_report
