-- Cross-model consistency: the hourly sales report, summed per day, must equal the
-- daily sales report for the same day. They diverged once because rpt_sales_by_hour
-- filtered out returns (GROSS) while rpt_daily_sales nets them (NET). This test fails
-- if that drift ever returns. Tolerance of 0.01 absorbs float rounding only.
with daily as (
    select sale_date as d, sum(total_sales_amount) as amt
    from {{ ref('rpt_daily_sales') }}
    group by sale_date
),

hourly as (
    select receipt_date as d, sum(sales_amount) as amt
    from {{ ref('rpt_sales_by_hour') }}
    group by receipt_date
)

select
    coalesce(daily.d, hourly.d)          as sale_date,
    daily.amt                            as daily_amount,
    hourly.amt                           as hourly_amount,
    coalesce(hourly.amt, 0) - coalesce(daily.amt, 0) as diff
from daily
full outer join hourly on daily.d = hourly.d
where abs(coalesce(hourly.amt, 0) - coalesce(daily.amt, 0)) > 0.01
