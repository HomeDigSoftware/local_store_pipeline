-- Guards the per-shift payroll identity: total_pay must equal the sum of the
-- three overtime-tier pay components to the cent. Any drift means the tier math
-- or rounding in int_workforce__shift_pay regressed.

select
    employee_id,
    shift_date,
    total_pay,
    regular_pay + ot125_pay + ot150_pay as component_sum
from {{ ref('int_workforce__shift_pay') }}
where abs(total_pay - (regular_pay + ot125_pay + ot150_pay)) > 0.001
