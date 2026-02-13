{{ config(materialized='view') }}


WITH OrderedAttendance AS (
    SELECT
        Employee_ID,
		Employee_Name,
        MovementType,
        AttendanceDateTime,
        SourceSequence,

        ROW_NUMBER() OVER (
            PARTITION BY Employee_ID
            ORDER BY AttendanceDateTime
        ) AS rn
    FROM {{ source('store_data', 'Fact_Attendance_Event') }}
    WHERE MovementType IN (1, 2, 91, 92)
)
SELECT
    i.Employee_ID
	,i.Employee_Name

	--,FORMAT(CAST(i.AttendanceDateTime AS TIME), N'hh\:mm') as ShiftStartTime
	--,FORMAT(CAST(o.AttendanceDateTime AS TIME), N'hh\:mm') as ShiftEndTime

    ,CAST(i.AttendanceDateTime AS DATE) AS ShiftDate


	,FORMAT(CAST(i.AttendanceDateTime AS TIME), N'hh\:mm') AS Shift_Start_Time
	,FORMAT(CAST(o.AttendanceDateTime AS TIME), N'hh\:mm') AS Shift_End_Time
	
    ,RIGHT('00' + CAST(DATEDIFF(MINUTE, i.AttendanceDateTime, o.AttendanceDateTime) / 60 AS VARCHAR(2)), 2)
			+ ':' +
	RIGHT('00' + CAST(DATEDIFF(MINUTE, i.AttendanceDateTime, o.AttendanceDateTime) % 60 AS VARCHAR(2)), 2)
     AS ShiftDuration_HHMM
    
    ,DATEPART(HOUR, i.AttendanceDateTime) AS ShiftStartHour
    ,DATEPART(HOUR, o.AttendanceDateTime) AS ShiftEndHour

    ,DATEDIFF(MINUTE, i.AttendanceDateTime, o.AttendanceDateTime)
        AS ShiftDurationMinutes
    
    ,CAST(
        DATEDIFF(MINUTE, i.AttendanceDateTime, o.AttendanceDateTime) / 60.0
        AS DECIMAL(5,2)
    ) AS ShiftDurationHours


    ,i.SourceSequence AS StartSequence
    ,o.SourceSequence AS EndSequence

    ,CASE
        WHEN CAST(i.AttendanceDateTime AS DATE)
           <> CAST(o.AttendanceDateTime AS DATE)
        THEN 1 ELSE 0
    END AS IsCrossMidnight

    ,CASE
        WHEN i.MovementType IN (91, 92)
          OR o.MovementType IN (91, 92)
        THEN 1 ELSE 0
    END AS IsManualCorrection

FROM OrderedAttendance i
JOIN OrderedAttendance o
  ON i.Employee_ID = o.Employee_ID
  AND o.rn = i.rn + 1
WHERE i.MovementType IN (1, 91)   -- IN
  AND o.MovementType IN (2, 92);  -- OUT #}

