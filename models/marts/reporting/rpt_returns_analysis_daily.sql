{{ config(materialized='table') }}

with returns as (
	select
		receipt_date,
		item_id,
		document_id,
		abs(quantity) as return_qty,
		abs(net_sales_amount) as return_amount
	from {{ ref('fct_sales') }}
	where is_return = 1
),

product_attributes as (
	select
		item_id,
		item_name,
		product_category_id,
		category_name as product_category_name
	from {{ ref('dim_product') }}
),

returns_analysis as (
	select
		returns.receipt_date,
		returns.item_id,
		product_attributes.item_name,
		product_attributes.product_category_id,
		product_attributes.product_category_name,
		sum(returns.return_qty) as return_qty,
		sum(returns.return_amount) as return_amount,
		count(distinct returns.document_id) as return_ticket_count,
		current_timestamp as dbt_loaded_at,
		'rpt_returns_analysis_daily' as dbt_source_relation
	from returns
	left join product_attributes
		on returns.item_id = product_attributes.item_id
	group by
		returns.receipt_date,
		returns.item_id,
		product_attributes.item_name,
		product_attributes.product_category_id,
		product_attributes.product_category_name
)

select *
from returns_analysis
