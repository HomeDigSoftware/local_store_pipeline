

select 
  i.*
  ,t.ItemDesc
from {{ source('store_data', 'Inventory') }} i
left join {{ source('store_data', 'Items') }} t on i.Item_ID = t.Item_ID 
where ItemDesc = 'שוקו חם גדול'
