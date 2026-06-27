{{ config(materialized='table', indexes=[{'columns': ['day_of_week', 'sales_hour'], 'unique': true}]) }}

-- Sales aggregated to (day_of_week x hour-of-day), powering an hour x weekday
-- staffing heatmap (critique #12). Requested by the website agent as
-- rpt_sales_by_hour_weekday.
--   day_of_week : Postgres DOW convention -> 0=Sunday ... 6=Saturday.
--   day_name    : English day name (UI renders RTL where needed).
--   occurrences : count of that weekday with sales activity in the window, so the
--                 UI can show a per-occurrence ("typical Friday 14:00") average
--                 via net_sales_amount / occurrences.
-- Window: full available history (same scope as rpt_sales_by_hour). Net of returns
-- (returns are negative in fct_sales), consistent with rpt_daily_sales.

with sales as (
	select
		receipt_date,
		extract(hour from receipt_datetime)::int as sales_hour,
		document_id,
		net_sales_amount
	from {{ ref('fct_sales') }}
),

date_dim as (
	select
		date_actual,
		day_of_week_number,
		day_name
	from {{ ref('dim_date') }}
),

sales_dated as (
	select
		sales.receipt_date,
		date_dim.day_of_week_number::int as day_of_week,
		trim(date_dim.day_name) as day_name,
		sales.sales_hour,
		sales.document_id,
		sales.net_sales_amount
	from sales
	join date_dim
		on sales.receipt_date = date_dim.date_actual
),

dow_occurrences as (
	select
		day_of_week,
		count(distinct receipt_date) as occurrences
	from sales_dated
	group by day_of_week
),

by_dow_hour as (
	select
		day_of_week,
		max(day_name) as day_name,
		sales_hour,
		sum(net_sales_amount) as net_sales_amount,
		count(distinct document_id) as tickets_count
	from sales_dated
	group by day_of_week, sales_hour
)

select
	by_dow_hour.day_of_week,
	by_dow_hour.day_name,
	by_dow_hour.sales_hour,
	by_dow_hour.net_sales_amount,
	by_dow_hour.tickets_count,
	dow_occurrences.occurrences,
	current_timestamp as dbt_loaded_at,
	'rpt_sales_by_hour_weekday' as dbt_source_relation
from by_dow_hour
join dow_occurrences
	on by_dow_hour.day_of_week = dow_occurrences.day_of_week
order by by_dow_hour.day_of_week, by_dow_hour.sales_hour
