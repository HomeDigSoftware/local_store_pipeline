{{ config(materialized='table') }}

with source_data as (
	select *
	from {{ source('store_data', 'items') }}
),

cleaned_items as (
	select
		item_id,
		itemdesc as item_name,
		itemtype as item_type_id,
		costperunit::numeric(18, 2) as cost_per_unit,
		(costperunit * 1.18)::numeric(18, 2) as cost_per_unit_inc_vat,
		price1::numeric(18, 2) as sale_price,
		(price1 - (costperunit * 1.18))::numeric(18, 2) as profit_per_unit_inc_vat,
		current_timestamp as dbt_loaded_at,
		'stg_store_data__items' as dbt_source_relation
	from source_data
	where item_id is not null
)

select *
from cleaned_items
