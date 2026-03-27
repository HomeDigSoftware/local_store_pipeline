{{ config(materialized='table') }}


SELECT
    e.emplyee_id,
    en.longname,
    movementtype,

    -- Date + HourTime (seconds since midnight)
    datesetting::timestamp + (hourtime || ' seconds')::interval AS attendancedatetime,

    datesetting::date AS attendancedate,

    (make_time(0, 0, 0) + (hourtime || ' seconds')::interval)::time AS attendancetime,

    hourtime / 3600 AS hourofday,

    hourtime / 60 AS minuteofday,

    attendancerecordingtype,
    front_office,
    e.s__sequence,
    mark,
    exceeded
FROM {{ source('store_data', 'employeesattendance') }} e
left join {{ source('store_data', 'employeesselection_byentrance') }} en on e.emplyee_id = en.emplyeenumber
