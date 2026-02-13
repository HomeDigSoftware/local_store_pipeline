{{ config(materialized='view') }}

SELECT
    Emplyee_ID,
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
    s__sequence,
    Mark,
    Exceeded
FROM EmployeesAttendance;