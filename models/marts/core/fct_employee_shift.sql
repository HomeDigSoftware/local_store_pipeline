{{ config(materialized='table') }}

with shifts as (
	select *
	from {{ ref('int_workforce__shift_pay') }}
),

employee_shift_fact as (
	select
		md5(
			concat_ws(
				'||',
				coalesce(employee_id::text, ''),
				coalesce(shift_date::text, ''),
				coalesce(shift_start_time::text, ''),
				coalesce(shift_end_time::text, ''),
				coalesce(start_sequence::text, ''),
				coalesce(end_sequence::text, '')
			)
		) as shift_key,
		employee_id,
		employee_name,
		shift_date,
		shift_start_time,
		shift_end_time,
		shift_duration_minutes,
		shift_duration_hours,
		shift_duration_hhmm,
		shift_start_hour,
		shift_end_hour,
		start_sequence,
		end_sequence,
		is_cross_midnight,
		is_manual_correction,
		-- payroll (from int_workforce__shift_pay)
		hourly_rate,
		regular_hours,
		ot125_hours,
		ot150_hours,
		regular_pay,
		ot125_pay,
		ot150_pay,
		total_pay,
		current_timestamp as dbt_loaded_at,
		'fct_employee_shift' as dbt_source_relation
	from shifts
)

select *
from employee_shift_fact
