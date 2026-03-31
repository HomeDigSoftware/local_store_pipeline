{{ config(materialized='table') }}

with source_data as (
	select *
	from {{ source('store_data', 'documents') }}
),

cleaned_documents as (
	select
		document_id,
		recordingdate::date as receipt_date,
		case
			when recordingdate is not null and printtime is not null then
				date_trunc('day', recordingdate::timestamp)
				+ (printtime * interval '1 second')
		end as receipt_datetime,
		case
			when printtime is not null then
				to_char(
					timestamp '2000-01-01' + (printtime * interval '1 second'),
					'HH24:MI:SS'
				)
		end as receipt_time,
		documenttype as document_type,
		generaltotalincludevat::numeric(18, 2) as total_amount_inc_vat,
		s__sequence as source_sequence,
		current_timestamp as dbt_loaded_at,
		'stg_store_data__documents' as dbt_source_relation
	from source_data
	where document_id is not null
)

select *
from cleaned_documents
