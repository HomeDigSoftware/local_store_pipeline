{{ config(materialized='table', indexes=[{'columns': ['item_id'], 'unique': true}, {'columns': ['category_name']}]) }}

with current_stock as (
	select *
	from {{ ref('int_inventory__current_stock') }}
),

dim_product as (
	select
		md5(coalesce(item_id::text, '')) as product_key,
		item_id,
		-- Placeholders for unmapped/deleted POS products (orphan item_ids). Parenthesised
		-- so the dashboard reads them as intentional, not as junk "Unknown Item" rows.
		coalesce(item_name, '(unmapped item)') as item_name,
		product_category_id,
		coalesce(product_category_name, '(uncategorized)') as category_name,
		unit_cost,
		unit_cost_inc_vat,
		unit_sale_price,
		profit_per_unit_inc_vat,
		current_timestamp as dbt_loaded_at,
		'dim_product' as dbt_source_relation
	from current_stock
)

select *
from dim_product
