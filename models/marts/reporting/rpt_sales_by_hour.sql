{{ config(materialized='table') }}

with sales as (
	select
		receipt_date,
		extract(hour from receipt_datetime)::int as sales_hour,
		document_id,
		quantity,
		net_sales_amount
	from {{ ref('fct_sales') }}
	-- Include returns (negative net_sales_amount/quantity) so hourly sums are NET of
	-- returns, consistent with int_sales__daily_store / rpt_daily_sales. Filtering
	-- is_return out made this report GROSS and ~returns-amount higher than the daily KPI.
),

date_dim as (
	select
		date_actual,
		day_name
	from {{ ref('dim_date') }}
),

by_hour as (
	select
		receipt_date,
		sales_hour,
		sum(net_sales_amount) as sales_amount,
		count(distinct document_id) as ticket_count,
		sum(quantity) as units_sold
	from sales
	group by receipt_date, sales_hour
),

sales_by_hour as (
	select
		by_hour.receipt_date,
		by_hour.sales_hour,
		date_dim.day_name as day_of_week_name,
		by_hour.sales_amount,
		by_hour.ticket_count,
		by_hour.units_sold,
		case
			when by_hour.ticket_count = 0 then null
			else by_hour.sales_amount / by_hour.ticket_count::numeric
		end as avg_ticket_amount,
		current_timestamp as dbt_loaded_at,
		'rpt_sales_by_hour' as dbt_source_relation
	from by_hour
	left join date_dim
		on by_hour.receipt_date = date_dim.date_actual
)

select *
from sales_by_hour
