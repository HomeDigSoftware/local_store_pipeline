{{ config(materialized='table') }}

with product_velocity as (
	select *
	from {{ ref('int_inventory__product_velocity') }}
),

stock_health as (
	select
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
		case
			when current_inventory_qty <= 0 then 'OUT_OF_STOCK'
			when sold_qty_30d = 0 then 'DEAD_STOCK'
			when days_of_cover_30d < 7 then 'STOCKOUT_RISK'
			when days_of_cover_30d > 90 then 'OVERSTOCK'
			else 'HEALTHY'
		end as stock_status,
		current_timestamp as dbt_loaded_at,
		'int_inventory__stock_health' as dbt_source_relation
	from product_velocity
)

select *
from stock_health
