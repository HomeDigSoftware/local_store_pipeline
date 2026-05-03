{{
  config(
    materialized = 'table',
    )
}}

with staged_inventory as (
  select *
  from {{ ref('stg_store_data__inventory') }}
)

select 
  item_id
  ,opening_inventory_qty as openinginventory
  ,inventory_balance_qty as inventorybalance
  ,counted_inventory_qty as countedinventory
  ,product_category_name as category
  ,item_name as itemdesc
  ,profit_per_unit_inc_vat as profit_per_unit_incvat
  ,unit_cost as cost
  ,unit_cost_inc_vat as costperunit_incvat
  ,unit_sale_price as sale_price
  ,product_category_id as category_id
from staged_inventory
order by item_id