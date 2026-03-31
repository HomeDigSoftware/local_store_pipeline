

select
    *
from {{ source('store_data', 'items') }}