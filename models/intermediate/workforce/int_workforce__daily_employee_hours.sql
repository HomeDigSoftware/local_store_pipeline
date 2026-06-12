{{ config(materialized='table') }}

with shifts as (
	select *
	from {{ ref('int_workforce__shifts') }}
),

daily_employee_hours_base as (
	select
		shift_date,
		employee_id,
		sum(shift_duration_minutes) as total_shift_minutes,
		sum(shift_duration_hours) as total_shift_hours,
		count(*) as shift_count
	from shifts
	group by shift_date, employee_id
),

daily_employee_hours as (
	select
		shift_date,
		employee_id,
		total_shift_minutes,
		total_shift_hours,
		shift_count
	from daily_employee_hours_base
)

select *
from daily_employee_hours
