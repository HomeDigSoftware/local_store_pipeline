{{ config(materialized='table') }}

with line_items as (
	select *
	from {{ ref('int_sales__line_items') }}
),

daily_product as (
	select
		receipt_date as sale_date,
		item_id,
		sum(quantity) as sold_qty,
		sum(line_total_inc_vat) as net_sales_amount,
		sum(case when is_return = 1 then quantity else 0 end) as return_qty,
		count(distinct document_id) as tickets_count
	from line_items
	group by receipt_date, item_id
)

select *
from daily_product
