{{ config(materialized='table') }}

with daily_employee_hours as (
    select *
    from {{ ref('int_workforce__daily_employee_hours') }}
),

daily_store_sales as (
    select *
    from {{ ref('int_sales__daily_store') }}
),

daily_store_hours as (
    select
        shift_date,
        sum(total_shift_minutes) as store_total_shift_minutes,
        sum(total_shift_hours) as store_total_shift_hours
    from daily_employee_hours
    group by shift_date
),

daily_sales_attribution as (
    select
        daily_employee_hours.shift_date,
        daily_employee_hours.employee_id,
        daily_employee_hours.total_shift_minutes,
        daily_employee_hours.total_shift_hours,
        daily_employee_hours.shift_count,
        coalesce(daily_store_sales.total_sales_amount, 0) as store_sales_amount,
        coalesce(daily_store_sales.total_units_sold, 0) as store_units_sold,
        coalesce(daily_store_sales.ticket_count, 0) as store_ticket_count,
        daily_store_hours.store_total_shift_minutes,
        daily_store_hours.store_total_shift_hours,
        case
            when coalesce(daily_store_hours.store_total_shift_hours, 0) > 0
                then daily_employee_hours.total_shift_hours / nullif(daily_store_hours.store_total_shift_hours, 0)
            else 0
        end as labor_share_ratio,
        case
            when coalesce(daily_store_hours.store_total_shift_hours, 0) > 0
                then coalesce(daily_store_sales.total_sales_amount, 0)
                    * (daily_employee_hours.total_shift_hours / nullif(daily_store_hours.store_total_shift_hours, 0))
            else 0
        end as attributed_sales_amount,
        case
            when coalesce(daily_employee_hours.total_shift_hours, 0) > 0
                then (
                    coalesce(daily_store_sales.total_sales_amount, 0)
                    * (daily_employee_hours.total_shift_hours / nullif(daily_store_hours.store_total_shift_hours, 0))
                ) / nullif(daily_employee_hours.total_shift_hours, 0)
            else null
        end as sales_per_hour,
        current_timestamp as dbt_loaded_at,
        'int_workforce__daily_sales_attribution' as dbt_source_relation
    from daily_employee_hours
    left join daily_store_sales
        on daily_employee_hours.shift_date = daily_store_sales.sale_date
    left join daily_store_hours
        on daily_employee_hours.shift_date = daily_store_hours.shift_date
)

select *
from daily_sales_attribution