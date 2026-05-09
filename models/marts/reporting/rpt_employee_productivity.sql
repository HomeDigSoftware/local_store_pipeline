{{ config(materialized='table') }}

with daily_employee_hours as (
	select *
	from {{ ref('int_workforce__daily_employee_hours') }}
),

employees as (
	select *
	from {{ ref('dim_employee') }}
),

employee_productivity_report as (
	select
		daily_employee_hours.shift_date,
		daily_employee_hours.employee_id,
		employees.employee_name,
		daily_employee_hours.total_shift_minutes,
		daily_employee_hours.total_shift_hours as hours_worked,
		daily_employee_hours.shift_count,
		cast(null as numeric(18, 2)) as sales_per_hour
	from daily_employee_hours
	left join employees
		on daily_employee_hours.employee_id = employees.employee_id
)

select *
from employee_productivity_report
