{{ config(materialized='table') }}

with staged_attendance_events as (
    select *
    from {{ ref('stg_store_data__attendance_events') }}
)

SELECT
    attendance_date AS attendancedate,
    case 
        when movement_type in (1, 91) then  ' IN'
        when movement_type in (2, 92) then  ' OUT'
        else 'UNKNOWN'
    end as action_type,
    attendance_time AS attendancetime,
    attendance_datetime AS attendancedatetime,
    employee_id as emplyee_id,
    employee_name as longname,
    movement_type as movementtype,

    -- Date + HourTime (seconds since midnight)



    extract(hour from attendance_time) AS hourofday,

    ((extract(hour from attendance_time) * 60) + extract(minute from attendance_time)) AS minuteofday,

    recording_type as attendancerecordingtype,
    front_office,
    source_sequence as s__sequence,
    mark,
    exceeded
FROM staged_attendance_events
