{{ config(materialized='table') }}

with source_data as (
	select *
	from {{ source('store_data', 'documentlines') }}
),

cleaned_document_lines as (
	select
		document_id,
		item_id,
		details as item_name,
		itemsqty::numeric(18, 3) as quantity,
		totalperline_incvat::numeric(18, 2) as line_total_inc_vat,
		current_timestamp as dbt_loaded_at,
		'stg_store_data__document_lines' as dbt_source_relation
	from source_data
	where document_id is not null
	  and item_id is not null
)

select *
from cleaned_document_lines
