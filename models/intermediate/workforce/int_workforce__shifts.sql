{{ config(materialized='table') }}


with staged_attendance_events as (
    select *
    from {{ ref('stg_store_data__attendance_events') }}
),

OrderedAttendance AS (
    SELECT
        employee_id,
        employee_name,
        movement_type,
        attendance_datetime,
        source_sequence,
        case 
            when movement_type in (1, 91) then  ' IN'
            when movement_type in (2, 92) then  ' OUT'
        else 'UNKNOWN'
            end as action_type,
        ROW_NUMBER() OVER (
            PARTITION BY employee_id
            ORDER BY attendance_datetime
        ) AS rn
    FROM staged_attendance_events
    WHERE movement_type IN (1, 2, 91, 92)
)
SELECT
     i.employee_id
    ,i.employee_name

    ,i.attendance_datetime::date AS shiftdate
    ,to_char(i.attendance_datetime::time, 'HH24:MI') AS shift_start_time
    ,to_char(o.attendance_datetime::time, 'HH24:MI') AS shift_end_time

    ,lpad(
        (EXTRACT(EPOCH FROM (o.attendance_datetime - i.attendance_datetime))::int / 60 / 60)::text,
        2, '0'
     ) || ':' ||
     lpad(
        (EXTRACT(EPOCH FROM (o.attendance_datetime - i.attendance_datetime))::int / 60 % 60)::text,
        2, '0'
     ) AS shiftduration_hhmm

    ,EXTRACT(HOUR FROM i.attendance_datetime)::int AS shiftstarttour
    ,EXTRACT(HOUR FROM o.attendance_datetime)::int AS shiftendtour

    ,EXTRACT(EPOCH FROM (o.attendance_datetime - i.attendance_datetime))::int / 60
        AS shiftdurationminutes

    ,ROUND(
        (EXTRACT(EPOCH FROM (o.attendance_datetime - i.attendance_datetime)) / 3600)::numeric,
        2
    ) AS shiftdurationhours

    ,i.source_sequence AS startsequence
    ,o.source_sequence AS endsequence

    ,CASE
        WHEN i.attendance_datetime::date <> o.attendance_datetime::date
        THEN 1 ELSE 0
    END AS iscrossmidnight

    ,CASE
        WHEN i.movement_type IN (91, 92)
          OR o.movement_type IN (91, 92)
        THEN 1 ELSE 0
    END AS ismanualcorrection

FROM OrderedAttendance i
JOIN OrderedAttendance o
  ON i.employee_id = o.employee_id
  AND o.rn = i.rn + 1
WHERE i.movement_type IN (1, 91)   -- IN
  AND o.movement_type IN (2, 92)  -- OUT

