{{
  config(
    materialized = 'table',
    )
}}

select 
    i.item_id
    ,i.openinginventory
    ,i.inventorybalance
    ,i.countedinventory
    ,itt.typedesc as category
    ,t.itemdesc
    ,cast(t.price1 - (t.costperunit * 1.18) as decimal(10,2)) as profit_per_unit_incvat
    ,t.costperunit as cost
    ,t.costperunit * 1.18 as costperunit_incvat
    ,t.price1 as sale_price
    ,t.itemtype as category_id
from {{ source('store_data', 'inventory') }} i
left join {{ source('store_data', 'items') }} t on i.item_id = t.item_id 
left join {{ source('store_data', 'itemtypes') }} itt on t.itemtype = itt.type_id
where i.card_id = 11 and i.cardsgroup = 3
order by i.item_id