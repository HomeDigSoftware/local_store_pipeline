{{ config(materialized='table') }}

with stock_health as (
	select *
	from {{ ref('int_inventory__stock_health') }}
),

inventory_snapshot_fact as (
	select
		current_date as snapshot_date,
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
	from stock_health
)

select *
from inventory_snapshot_fact
