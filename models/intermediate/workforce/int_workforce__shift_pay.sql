{{ config(materialized='table') }}

-- Per-shift payroll with Israeli-style overtime tiers, applied to each shift's
-- worked hours and hard-capped at 12h (the attendance generator never produces a
-- longer shift):
--   hours 1-8   -> x1.00 (regular)
--   hours 9-10  -> x1.25
--   hours 11-12 -> x1.50
-- shift_duration_hours is already rounded to 2dp upstream, so the three tier-hour
-- buckets sum back to it exactly, and total_pay = regular_pay + ot125_pay +
-- ot150_pay holds to the cent (the components are each rounded, then summed).

with shifts as (
    select *
    from {{ ref('int_workforce__shifts') }}
),

wages as (
    select
        employee_id,
        hourly_rate
    from {{ ref('employee_wages') }}
),

shift_pay as (
    select
        shifts.*,
        wages.hourly_rate,

        least(shifts.shift_duration_hours, 8)::numeric                    as regular_hours,
        greatest(0, least(shifts.shift_duration_hours, 10) - 8)::numeric  as ot125_hours,
        greatest(0, least(shifts.shift_duration_hours, 12) - 10)::numeric as ot150_hours,

        round((least(shifts.shift_duration_hours, 8) * wages.hourly_rate)::numeric, 2)
            as regular_pay,
        round((greatest(0, least(shifts.shift_duration_hours, 10) - 8) * wages.hourly_rate * 1.25)::numeric, 2)
            as ot125_pay,
        round((greatest(0, least(shifts.shift_duration_hours, 12) - 10) * wages.hourly_rate * 1.50)::numeric, 2)
            as ot150_pay,

        current_timestamp as dbt_loaded_at,
        'int_workforce__shift_pay' as dbt_source_relation
    from shifts
    left join wages
        on shifts.employee_id = wages.employee_id
)

select
    *,
    (regular_pay + ot125_pay + ot150_pay) as total_pay
from shift_pay
