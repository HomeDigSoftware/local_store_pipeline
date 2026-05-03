{{ config(materialized='table') }}

with inventory as (
	select *
	from {{ source('store_data', 'inventory') }}
),

items as (
	select *
		from {{ ref('stg_store_data__items') }}
),

item_types as (
	select *
		from {{ ref('stg_store_data__item_types') }}
),

cleaned_inventory as (
	select
		inventory.item_id,
		inventory.openinginventory::numeric(18, 3) as opening_inventory_qty,
		inventory.inventorybalance::numeric(18, 3) as inventory_balance_qty,
		inventory.countedinventory::numeric(18, 3) as counted_inventory_qty,
		items.item_type_id as product_category_id,
		item_types.item_type_name as product_category_name,
		items.item_name,
		items.cost_per_unit as unit_cost,
		items.cost_per_unit_inc_vat as unit_cost_inc_vat,
		items.sale_price as unit_sale_price,
		items.profit_per_unit_inc_vat,
		current_timestamp as dbt_loaded_at,
		'stg_store_data__inventory' as dbt_source_relation
	from inventory
	left join items
		on inventory.item_id = items.item_id
	left join item_types
		on items.item_type_id = item_types.item_type_id
	where inventory.card_id = 11
	  and inventory.cardsgroup = 3
	  and inventory.item_id is not null
)

select *
from cleaned_inventory
