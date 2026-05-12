{{ config(materialized='table') }}

with inventory_risk as (
	select *
	from {{ ref('rpt_inventory_risk') }}
),

product_velocity as (
	select *
	from {{ ref('rpt_product_velocity') }}
),

inventory_actions as (
	select
		product_velocity.snapshot_date,
		product_velocity.item_id,
		product_velocity.item_name,
		product_velocity.product_category_id,
		product_velocity.product_category_name,
		product_velocity.current_inventory_qty,
		product_velocity.sold_qty_7d,
		product_velocity.sold_qty_30d,
		product_velocity.days_of_cover_30d,
		product_velocity.velocity_band,
		coalesce(inventory_risk.stock_status, 'HEALTHY') as stock_status,
		case
			when coalesce(inventory_risk.stock_status, 'HEALTHY') in ('OUT_OF_STOCK', 'STOCKOUT_RISK') then true
			else false
		end as reorder_flag,
		case
			when coalesce(inventory_risk.stock_status, 'HEALTHY') = 'OVERSTOCK' then true
			else false
		end as overstock_flag,
		case
			when coalesce(inventory_risk.stock_status, 'HEALTHY') = 'DEAD_STOCK' then true
			else false
		end as dead_stock_flag,
		case
			when coalesce(inventory_risk.stock_status, 'HEALTHY') = 'OUT_OF_STOCK' then 1
			when coalesce(inventory_risk.stock_status, 'HEALTHY') = 'STOCKOUT_RISK' then 2
			when coalesce(inventory_risk.stock_status, 'HEALTHY') = 'DEAD_STOCK' then 3
			when coalesce(inventory_risk.stock_status, 'HEALTHY') = 'OVERSTOCK' then 4
			else 5
		end as action_priority,
		case
			when coalesce(inventory_risk.stock_status, 'HEALTHY') = 'OUT_OF_STOCK' then 'Reorder immediately'
			when coalesce(inventory_risk.stock_status, 'HEALTHY') = 'STOCKOUT_RISK' then 'Reorder soon'
			when coalesce(inventory_risk.stock_status, 'HEALTHY') = 'DEAD_STOCK' then 'Review markdown or promotion'
			when coalesce(inventory_risk.stock_status, 'HEALTHY') = 'OVERSTOCK' then 'Reduce purchasing and monitor sell-through'
			else 'No action needed'
		end as recommended_action,
		current_timestamp as dbt_loaded_at,
		'rpt_inventory_actions' as dbt_source_relation
	from product_velocity
	left join inventory_risk
		on product_velocity.snapshot_date = inventory_risk.snapshot_date
		and product_velocity.item_id = inventory_risk.item_id
)

select *
from inventory_actions