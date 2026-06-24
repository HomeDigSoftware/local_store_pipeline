{{ config(materialized='table') }}

-- One row per employee: a workforce productivity + labor-cost scorecard.
-- Combines per-shift payroll (int_workforce__shift_pay) with the hours-share
-- sales attribution (int_workforce__daily_sales_attribution), then ranks the
-- staff by sales, hours and labor efficiency and adds a trailing 7-day "recent
-- form" average. Surfaced on the dashboard exposure.

with shift_pay as (
    select *
    from {{ ref('int_workforce__shift_pay') }}
),

attribution as (
    select *
    from {{ ref('int_workforce__daily_sales_attribution') }}
),

employees as (
    select *
    from {{ ref('dim_employee') }}
),

pay_by_employee as (
    select
        employee_id,
        count(*)                  as total_shifts,
        sum(shift_duration_hours) as total_hours,
        sum(regular_hours)        as regular_hours,
        sum(ot125_hours)          as ot125_hours,
        sum(ot150_hours)          as ot150_hours,
        sum(total_pay)            as total_pay,
        max(hourly_rate)          as hourly_rate
    from shift_pay
    group by employee_id
),

sales_by_employee as (
    select
        employee_id,
        sum(attributed_sales_amount) as attributed_sales
    from attribution
    group by employee_id
),

-- Recent form: average daily attributed sales / hours over the trailing 7
-- calendar days ending at the latest date present in the data.
recent_form as (
    select
        employee_id,
        avg(attributed_sales_amount) as avg_daily_sales_7d,
        avg(total_shift_hours)       as avg_daily_hours_7d
    from attribution
    where shift_date > (select max(shift_date) from attribution) - interval '7 days'
    group by employee_id
),

combined as (
    select
        pay_by_employee.employee_id,
        employees.employee_name,
        pay_by_employee.total_shifts,
        round(pay_by_employee.total_hours::numeric, 2)    as total_hours,
        round(pay_by_employee.regular_hours::numeric, 2)  as regular_hours,
        round(pay_by_employee.ot125_hours::numeric, 2)    as ot125_hours,
        round(pay_by_employee.ot150_hours::numeric, 2)    as ot150_hours,
        pay_by_employee.hourly_rate,
        round(pay_by_employee.total_pay::numeric, 2)      as total_pay,
        round((pay_by_employee.total_pay / nullif(pay_by_employee.total_hours, 0))::numeric, 2)
            as avg_hourly_cost,
        round(coalesce(sales_by_employee.attributed_sales, 0)::numeric, 2)
            as attributed_sales,
        round((coalesce(sales_by_employee.attributed_sales, 0)
               / nullif(pay_by_employee.total_pay, 0))::numeric, 2)
            as sales_per_labor_shekel,
        round(coalesce(recent_form.avg_daily_sales_7d, 0)::numeric, 2)
            as avg_daily_sales_7d,
        round(coalesce(recent_form.avg_daily_hours_7d, 0)::numeric, 2)
            as avg_daily_hours_7d
    from pay_by_employee
    left join employees
        on pay_by_employee.employee_id = employees.employee_id
    left join sales_by_employee
        on pay_by_employee.employee_id = sales_by_employee.employee_id
    left join recent_form
        on pay_by_employee.employee_id = recent_form.employee_id
)

select
    *,
    rank() over (order by attributed_sales desc)        as sales_rank,
    rank() over (order by total_hours desc)             as hours_rank,
    rank() over (order by sales_per_labor_shekel desc)  as efficiency_rank,
    current_timestamp as dbt_loaded_at,
    'rpt_workforce_productivity_summary' as dbt_source_relation
from combined
order by attributed_sales desc
