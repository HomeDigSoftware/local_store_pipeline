{{ config(materialized='table') }}

with line_items as (
	select *
	from {{ ref('int_sales__line_items') }}
),

returns as (
	select
		document_id,
		receipt_date,
		receipt_datetime,
		item_id,
		item_name,
		quantity as return_qty,
		line_total_inc_vat as return_amount,
		payment_type,
		is_credit,
		source_sequence,
		current_timestamp as dbt_loaded_at,
		'int_sales__returns' as dbt_source_relation
	from line_items
	where is_return = 1
)

select *
from returns
