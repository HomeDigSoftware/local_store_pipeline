{{ config(materialized='table') }}


WITH OrderedAttendance AS (
    SELECT
        employee_id,
        employee_name,
        movementtype,
        attendancedatetime,
        sourcesequence,
        case 
            when movementtype in (1, 91) then  ' IN'
            when movementtype in (2, 92) then  ' OUT'
        else 'UNKNOWN'
            end as action_type,
        ROW_NUMBER() OVER (
            PARTITION BY employee_id
            ORDER BY attendancedatetime
        ) AS rn
    FROM {{ source('store_data', 'fact_attendance_event') }}
    WHERE movementtype IN (1, 2, 91, 92)
)
SELECT
     i.employee_id
    ,i.employee_name

    ,i.attendancedatetime::date AS shiftdate
    ,to_char(i.attendancedatetime::time, 'HH24:MI') AS shift_start_time
    ,to_char(o.attendancedatetime::time, 'HH24:MI') AS shift_end_time

    ,lpad(
        (EXTRACT(EPOCH FROM (o.attendancedatetime - i.attendancedatetime))::int / 60 / 60)::text,
        2, '0'
     ) || ':' ||
     lpad(
        (EXTRACT(EPOCH FROM (o.attendancedatetime - i.attendancedatetime))::int / 60 % 60)::text,
        2, '0'
     ) AS shiftduration_hhmm

    ,EXTRACT(HOUR FROM i.attendancedatetime)::int AS shiftstarttour
    ,EXTRACT(HOUR FROM o.attendancedatetime)::int AS shiftendtour

    ,EXTRACT(EPOCH FROM (o.attendancedatetime - i.attendancedatetime))::int / 60
        AS shiftdurationminutes

    ,ROUND(
        (EXTRACT(EPOCH FROM (o.attendancedatetime - i.attendancedatetime)) / 3600)::numeric,
        2
    ) AS shiftdurationhours

    ,i.sourcesequence AS startsequence
    ,o.sourcesequence AS endsequence

    ,CASE
        WHEN i.attendancedatetime::date <> o.attendancedatetime::date
        THEN 1 ELSE 0
    END AS iscrossmidnight

    ,CASE
        WHEN i.movementtype IN (91, 92)
          OR o.movementtype IN (91, 92)
        THEN 1 ELSE 0
    END AS ismanualcorrection

FROM OrderedAttendance i
JOIN OrderedAttendance o
  ON i.employee_id = o.employee_id
  AND o.rn = i.rn + 1
WHERE i.movementtype IN (1, 91)   -- IN
  AND o.movementtype IN (2, 92)  -- OUT

