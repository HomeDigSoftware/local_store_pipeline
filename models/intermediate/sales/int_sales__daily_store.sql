{{ config(materialized='table') }}

with line_items as (
	select *
	from {{ ref('int_sales__line_items') }}
),

daily_store as (
	select
		receipt_date as sale_date,
		sum(line_total_inc_vat) as total_sales_amount,
		sum(quantity) as total_units_sold,
		count(distinct document_id) as ticket_count
	from line_items
	group by receipt_date
)

select *
from daily_store
