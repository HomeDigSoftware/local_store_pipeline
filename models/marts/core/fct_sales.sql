{{ config(materialized='table') }}

with line_items as (
	select *
	from {{ ref('int_sales__line_items') }}
),

sales_fact as (
	select
		md5(
			concat_ws(
				'||',
				coalesce(document_id::text, ''),
				coalesce(item_id::text, ''),
				coalesce(receipt_date::text, ''),
				coalesce(source_sequence::text, ''),
				coalesce(line_total_inc_vat::text, '')
			)
		) as sales_key,
		document_id,
		receipt_datetime,
		receipt_date,
		item_id,
		quantity,
		line_total_inc_vat as net_sales_amount,
		receipt_total_inc_vat as gross_sales_amount,
		is_return,
		payment_type,
		is_credit,
		source_sequence
	from line_items
)

select *
from sales_fact
