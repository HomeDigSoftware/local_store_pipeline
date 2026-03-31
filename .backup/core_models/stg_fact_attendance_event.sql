{{ config(materialized='table') }}


SELECT
    datesetting::date AS attendancedate,
    case 
        when movementtype in (1, 91) then  ' IN'
        when movementtype in (2, 92) then  ' OUT'
        else 'UNKNOWN'
    end as action_type,
    (make_time(0, 0, 0) + (hourtime || ' seconds')::interval)::time AS attendancetime,
    datesetting::timestamp + (hourtime || ' seconds')::interval AS attendancedatetime,
    e.emplyee_id,
    en.longname,
    movementtype,

    -- Date + HourTime (seconds since midnight)



    hourtime / 3600 AS hourofday,

    hourtime / 60 AS minuteofday,

    attendancerecordingtype,
    front_office,
    e.s__sequence,
    mark,
    exceeded
FROM {{ source('store_data', 'employeesattendance') }} e
left join {{ source('store_data', 'employeesselection_byentrance') }} en on e.emplyee_id = en.emplyeenumber
