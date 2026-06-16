-- Cross-model consistency: the employee labor-share attribution must distribute the
-- WHOLE of each day's store sales (the per-day ratios sum to 1). So for every day that
-- has attribution, sum(attributed_sales_amount) must equal the daily store total. This
-- fails if the attribution logic ever drifts (ratios stop summing to 1, or the store
-- total feeding the split diverges). Tolerance of 0.01 absorbs float rounding only.
--
-- INNER join on purpose: attribution exists only for days an employee worked, a subset
-- of all sale days — days with no shift legitimately have no attribution and are not a
-- violation, so they must not be flagged.
with attributed as (
    select shift_date as sale_date, sum(attributed_sales_amount) as attributed_amount
    from {{ ref('int_workforce__daily_sales_attribution') }}
    group by shift_date
),

store as (
    select sale_date, total_sales_amount as store_amount
    from {{ ref('int_sales__daily_store') }}
)

select
    attributed.sale_date,
    attributed.attributed_amount,
    store.store_amount,
    attributed.attributed_amount - store.store_amount as diff
from attributed
join store on attributed.sale_date = store.sale_date
where abs(attributed.attributed_amount - store.store_amount) > 0.01
