{{ config(materialized='view') }}

select 
  i.*
  ,t.itemdesc
from {{ source('store_data', 'inventory') }} i
left join {{ source('store_data', 'items') }} t on i.item_id = t.item_id 
where t.itemdesc = 'שוקו חם גדול'



