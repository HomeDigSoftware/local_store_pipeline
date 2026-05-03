{{ config(materialized='table') }}

with daily_store as (
	select *
	from {{ ref('int_sales__daily_store') }}
),

daily_sales_report as (
	select
		sale_date,
		total_sales_amount,
		total_units_sold,
		ticket_count,
		case
			when ticket_count = 0 then null
			else total_sales_amount / ticket_count
		end as avg_ticket_amount
	from daily_store
)

select *
from daily_sales_report
