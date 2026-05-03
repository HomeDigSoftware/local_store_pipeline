{{ config(materialized='table') }}

with attendance_events as (
	select *
	from {{ source('store_data', 'employeesattendance') }}
),

employee_reference as (
	select *
	from {{ ref('stg_store_data__employees') }}
),

cleaned_attendance_events as (
	select
		attendance_events.emplyee_id as employee_id,
		employee_reference.employee_name,
		attendance_events.datesetting::date as attendance_date,
		(make_time(0, 0, 0) + (attendance_events.hourtime || ' seconds')::interval)::time as attendance_time,
		attendance_events.datesetting::timestamp + (attendance_events.hourtime || ' seconds')::interval as attendance_datetime,
		attendance_events.movementtype as movement_type,
		attendance_events.attendancerecordingtype as recording_type,
		attendance_events.front_office,
		attendance_events.mark,
		attendance_events.exceeded,
		attendance_events.s__sequence as source_sequence,
		current_timestamp as dbt_loaded_at,
		'stg_store_data__attendance_events' as dbt_source_relation
	from attendance_events
	left join employee_reference
		on attendance_events.emplyee_id = employee_reference.employee_id
	where attendance_events.emplyee_id is not null
	  and attendance_events.datesetting is not null
	  and attendance_events.hourtime is not null
)

select *
from cleaned_attendance_events
