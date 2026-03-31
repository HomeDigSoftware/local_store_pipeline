{{ config(materialized='table') }}

with source_data as (
	select *
	from {{ source('store_data', 'receiptlines') }}
),

cleaned_receipt_lines as (
	select
		receipt_id as document_id,
		paymenttype as payment_type,
		case
			when paymenttype = 3 then 1
			else 0
		end as is_credit,
		creditcardtype as credit_card_type,
		accountnumber_moreinfo as account_number_moreinfo,
		current_timestamp as dbt_loaded_at,
		'stg_store_data__receipt_lines' as dbt_source_relation
	from source_data
	where receipt_id is not null
)

select *
from cleaned_receipt_lines
