{{ config(materialized='table') }}

with shifts as (
	select *
	from {{ ref('int_workforce__shifts') }}
),

employee_shift_fact as (
	select
		md5(
			concat_ws(
				'||',
				coalesce(employee_id::text, ''),
				coalesce(shiftdate::text, ''),
				coalesce(shift_start_time::text, ''),
				coalesce(shift_end_time::text, ''),
				coalesce(startsequence::text, ''),
				coalesce(endsequence::text, '')
			)
		) as shift_key,
		employee_id,
		employee_name,
		shiftdate as shift_date,
		shift_start_time,
		shift_end_time,
		shiftdurationminutes as shift_duration_minutes,
		shiftdurationhours as shift_duration_hours,
		shiftduration_hhmm as shift_duration_hhmm,
		shiftstarttour as shift_start_hour,
		shiftendtour as shift_end_hour,
		startsequence as start_sequence,
		endsequence as end_sequence,
		iscrossmidnight as is_cross_midnight,
		ismanualcorrection as is_manual_correction,
		current_timestamp as dbt_loaded_at,
		'fct_employee_shift' as dbt_source_relation
	from shifts
)

select *
from employee_shift_fact
