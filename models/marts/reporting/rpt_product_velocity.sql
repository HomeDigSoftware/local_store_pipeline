{{ config(materialized='table') }}

with inventory_snapshot as (
	select *
	from {{ ref('fct_inventory_snapshot') }}
),

product_velocity_report as (
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
		velocity_band
	from inventory_snapshot
)

select *
from product_velocity_report
