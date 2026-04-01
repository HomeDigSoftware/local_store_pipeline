{{ config(materialized='table') }}

with documents as (
	select *
	from {{ ref('stg_store_data__documents') }}
),

document_lines as (
	select *
	from {{ ref('stg_store_data__document_lines') }}
),

valid_receipt_lines as (
	select *
	from {{ ref('stg_store_data__receipt_lines') }}
	where coalesce(account_number_moreinfo, '') <> '2'
),

payment_context as (
	select
		document_id,
		min(payment_type) as payment_type,
		max(is_credit) as is_credit,
		min(credit_card_type) as credit_card_type
	from valid_receipt_lines
	group by document_id
),

line_items as (
	select
		documents.document_id,
		documents.receipt_datetime,
		documents.receipt_date,
		documents.receipt_time as sale_time,
		documents.document_type,
		document_lines.item_id,
		document_lines.item_name,
		document_lines.quantity,
		document_lines.line_total_inc_vat,
		documents.total_amount_inc_vat as receipt_total_inc_vat,
		payment_context.payment_type,
		payment_context.is_credit,
		payment_context.credit_card_type,
		case
			when documents.total_amount_inc_vat < 0 then 1
			else 0
		end as is_return,
		documents.source_sequence,
		current_timestamp as dbt_loaded_at,
		'int_sales__line_items' as dbt_source_relation
	from documents
	inner join document_lines
		on documents.document_id = document_lines.document_id
	inner join payment_context
		on documents.document_id = payment_context.document_id
)

select *
from line_items
