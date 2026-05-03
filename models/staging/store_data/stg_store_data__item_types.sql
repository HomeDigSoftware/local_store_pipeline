{{ config(materialized='table') }}

with source_data as (
	select *
	from {{ source('store_data', 'itemtypes') }}
),

cleaned_item_types as (
	select
		type_id as item_type_id,
		typedesc as item_type_name,
		current_timestamp as dbt_loaded_at,
		'stg_store_data__item_types' as dbt_source_relation
	from source_data
	where type_id is not null
)

select *
from cleaned_item_types
