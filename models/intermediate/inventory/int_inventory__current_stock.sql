{{ config(materialized='table') }}

with staged_inventory as (
	select *
	from {{ ref('stg_store_data__inventory') }}
),

current_stock as (
	select
		item_id,
		item_name,
		product_category_id,
		product_category_name,
		opening_inventory_qty,
		inventory_balance_qty,
		counted_inventory_qty,
		coalesce(counted_inventory_qty, inventory_balance_qty) as current_inventory_qty,
		case
			when counted_inventory_qty is not null then counted_inventory_qty - inventory_balance_qty
			else null
		end as inventory_gap_qty,
		unit_cost,
		unit_cost_inc_vat,
		unit_sale_price,
		profit_per_unit_inc_vat,
		coalesce(counted_inventory_qty, inventory_balance_qty) * coalesce(unit_cost, 0) as inventory_value_cost,
		coalesce(counted_inventory_qty, inventory_balance_qty) * coalesce(unit_sale_price, 0) as inventory_value_retail,
		current_timestamp as dbt_loaded_at,
		'int_inventory__current_stock' as dbt_source_relation
	from staged_inventory
)

select *
from current_stock
