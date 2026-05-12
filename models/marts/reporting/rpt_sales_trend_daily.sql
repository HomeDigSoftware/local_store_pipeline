{{ config(materialized='table') }}

with daily_sales as (
	select *
	from {{ ref('rpt_daily_sales') }}
),

date_dimension as (
	select *
	from {{ ref('dim_date') }}
),

sales_with_calendar as (
	select
		daily_sales.sale_date,
		date_dimension.day_name as day_of_week_name,
		date_part('week', daily_sales.sale_date) as week_of_year,
		date_dimension.month_name,
		date_dimension.year as year_number,
		daily_sales.total_sales_amount,
		daily_sales.total_units_sold,
		daily_sales.ticket_count,
		daily_sales.avg_ticket_amount
	from daily_sales
	left join date_dimension
		on daily_sales.sale_date = date_dimension.date_actual
),

sales_trend as (
	select
		sale_date,
		day_of_week_name,
		week_of_year,
		month_name,
		year_number,
		total_sales_amount,
		total_units_sold,
		ticket_count,
		avg_ticket_amount,
		lag(total_sales_amount) over (order by sale_date) as sales_prev_day,
		lag(total_sales_amount, 7) over (order by sale_date) as sales_prev_week_same_day,
		total_sales_amount - lag(total_sales_amount) over (order by sale_date) as sales_change_vs_prev_day,
		total_sales_amount - lag(total_sales_amount, 7) over (order by sale_date) as sales_change_vs_prev_week,
		avg(total_sales_amount) over (order by sale_date rows between 6 preceding and current row) as sales_7d_avg,
		avg(ticket_count) over (order by sale_date rows between 6 preceding and current row) as tickets_7d_avg,
		avg(avg_ticket_amount) over (order by sale_date rows between 6 preceding and current row) as avg_ticket_7d_avg,
		current_timestamp as dbt_loaded_at,
		'rpt_sales_trend_daily' as dbt_source_relation
	from sales_with_calendar
)

select *
from sales_trend