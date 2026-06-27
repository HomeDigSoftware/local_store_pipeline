{{ config(materialized='table', indexes=[{'columns': ['sales_hour'], 'unique': true}]) }}

-- Staffing coverage vs sales by hour-of-day ("are we staffed when busy?", critique
-- #15). Requested by the website agent as rpt_staffing_vs_sales_by_hour.
--   labour_hours  : total employee-hours present during each hour bucket, allocated
--                   from shift start/end (minute precision) by interval overlap.
--   headcount_avg : average simultaneous staff during that hour
--                   = labour_hours / number of distinct staffed days.
-- Both labour and sales are restricted to the date range present in BOTH facts, so
-- sales-per-labour-hour (computed UI-side as net_sales_amount / labour_hours) is
-- window-consistent. Cross-midnight shifts are extended by 24h and bucketed mod 24,
-- so post-midnight hours land in hour-of-day 0,1,2...

with shifts as (
	select
		shift_date,
		(split_part(shift_start_time, ':', 1)::int
			+ split_part(shift_start_time, ':', 2)::int / 60.0) as start_frac,
		(split_part(shift_end_time, ':', 1)::int
			+ split_part(shift_end_time, ':', 2)::int / 60.0)
			+ case when is_cross_midnight = 1 then 24 else 0 end as end_frac
	from {{ ref('fct_employee_shift') }}
	where shift_start_time is not null
	  and shift_end_time is not null
),

sales_hourly as (
	select
		receipt_date,
		extract(hour from receipt_datetime)::int as sales_hour,
		document_id,
		net_sales_amount
	from {{ ref('fct_sales') }}
),

-- overlapping date window so the sales-per-labour ratio is valid
bounds as (
	select
		greatest(
			(select min(shift_date) from shifts),
			(select min(receipt_date) from sales_hourly)
		) as start_date,
		least(
			(select max(shift_date) from shifts),
			(select max(receipt_date) from sales_hourly)
		) as end_date
),

shifts_win as (
	select shifts.*
	from shifts
	cross join bounds
	where shifts.shift_date between bounds.start_date and bounds.end_date
),

-- expand each shift into hour buckets, carrying the fraction of the hour worked
shift_hours as (
	select
		(h % 24) as sales_hour,
		shifts_win.shift_date,
		least(shifts_win.end_frac, h + 1) - greatest(shifts_win.start_frac, h) as overlap_hours
	from shifts_win
	cross join lateral generate_series(
		floor(shifts_win.start_frac)::int,
		ceil(shifts_win.end_frac)::int - 1
	) as h
	where least(shifts_win.end_frac, h + 1) - greatest(shifts_win.start_frac, h) > 0
),

labour_by_hour as (
	select
		sales_hour,
		sum(overlap_hours) as labour_hours,
		count(distinct shift_date) as staffed_days
	from shift_hours
	group by sales_hour
),

sales_win as (
	select sales_hourly.*
	from sales_hourly
	cross join bounds
	where sales_hourly.receipt_date between bounds.start_date and bounds.end_date
),

sales_by_hour as (
	select
		sales_hour,
		sum(net_sales_amount) as net_sales_amount,
		count(distinct document_id) as tickets_count
	from sales_win
	group by sales_hour
),

hours_spine as (
	select generate_series(0, 23) as sales_hour
)

select
	hours_spine.sales_hour,
	round(coalesce(labour_by_hour.labour_hours, 0)::numeric, 2) as labour_hours,
	case
		when labour_by_hour.staffed_days > 0
			then round((labour_by_hour.labour_hours / labour_by_hour.staffed_days)::numeric, 2)
		else 0
	end as headcount_avg,
	coalesce(sales_by_hour.net_sales_amount, 0) as net_sales_amount,
	coalesce(sales_by_hour.tickets_count, 0) as tickets_count,
	current_timestamp as dbt_loaded_at,
	'rpt_staffing_vs_sales_by_hour' as dbt_source_relation
from hours_spine
left join labour_by_hour
	on hours_spine.sales_hour = labour_by_hour.sales_hour
left join sales_by_hour
	on hours_spine.sales_hour = sales_by_hour.sales_hour
order by hours_spine.sales_hour
