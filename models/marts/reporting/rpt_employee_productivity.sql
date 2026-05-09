{{ config(materialized='table') }}

with daily_sales_attribution as (
	select *
	from {{ ref('int_workforce__daily_sales_attribution') }}
),

employees as (
	select *
	from {{ ref('dim_employee') }}
),

employee_productivity_report as (
	select
		daily_sales_attribution.shift_date,
		daily_sales_attribution.employee_id,
		employees.employee_name,
		daily_sales_attribution.total_shift_minutes,
		daily_sales_attribution.total_shift_hours as hours_worked,
		daily_sales_attribution.shift_count,
		daily_sales_attribution.attributed_sales_amount as sales_amount,
		daily_sales_attribution.sales_per_hour
	from daily_sales_attribution
	left join employees
		on daily_sales_attribution.employee_id = employees.employee_id
)

select *
from employee_productivity_report
