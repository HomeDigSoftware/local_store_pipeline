{{ config(materialized='table') }}

with staged_attendance_events as (
	select *
	from {{ ref('stg_store_data__attendance_events') }}
),

cleaned_attendance_events as (
	select
		employee_id,
		employee_name,
		attendance_date,
		attendance_time,
		attendance_datetime,
		movement_type,
		case
			when movement_type in (1, 91) then 'IN'
			when movement_type in (2, 92) then 'OUT'
			else 'UNKNOWN'
		end as action_type,
		case
			when movement_type in (91, 92) then 1
			else 0
		end as is_manual_correction,
		extract(hour from attendance_time)::int as hour_of_day,
		((extract(hour from attendance_time) * 60) + extract(minute from attendance_time))::int as minute_of_day,
		recording_type,
		front_office,
		mark,
		exceeded,
		source_sequence,
		current_timestamp as dbt_loaded_at,
		'int_workforce__attendance_events_clean' as dbt_source_relation
	from staged_attendance_events
	where movement_type in (1, 2, 91, 92)
)

select *
from cleaned_attendance_events
