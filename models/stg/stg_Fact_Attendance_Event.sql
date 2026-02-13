{{ config(materialized='view') }}


SELECT
    Emplyee_ID,
	en.LongName,
    MovementType,

    -- Date + HourTime (seconds since midnight)
    DATEADD(SECOND, HourTime, CAST(DateSetting AS DATETIME)) AS AttendanceDateTime,

    CAST(DateSetting AS DATE) AS AttendanceDate,

    CAST(
        DATEADD(SECOND, HourTime, '00:00:00')
        AS TIME
    ) AS AttendanceTime,

    HourTime / 3600 AS HourOfDay,

    HourTime / 60 AS MinuteOfDay,

    AttendanceRecordingType,
    FRONT_OFFICE,
    e.s__sequence,
    Mark,
    Exceeded
FROM {{ source('store_data', 'EmployeesAttendance') }} e
left join {{ source('store_data', 'EmployeesSelection_byEntrance') }} en on e.Emplyee_ID = en.EmplyeeNumber;
