{{
  config(
    materialized = 'table',
    )
}}

select 
    i.*
    ,t.itemdesc
from {{ source('store_data', 'inventory') }} i
left join {{ source('store_data', 'items') }} t on i.item_id = t.item_id 