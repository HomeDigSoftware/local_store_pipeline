{{ config(materialized='table') }}

with anchor_date as (
	select max(receipt_date) as as_of_date
	from {{ ref('fct_sales') }}
),

sales_30d as (
	select
		item_id,
		sum(net_sales_amount) as sales_amount_30d,
		sum(quantity) as units_sold_30d,
		count(distinct document_id) as ticket_count_30d
	from {{ ref('fct_sales') }}
	cross join anchor_date
	where receipt_date > anchor_date.as_of_date - interval '30 days'
	  and receipt_date <= anchor_date.as_of_date
	group by item_id
),

latest_velocity as (
	select *
	from {{ ref('rpt_inventory_actions') }}
	where snapshot_date = (select max(snapshot_date) from {{ ref('rpt_inventory_actions') }})
),

product_attributes as (
	select *
	from {{ ref('dim_product') }}
),

product_performance as (
	select
		product_attributes.item_id,
		product_attributes.item_name,
		product_attributes.product_category_id,
		product_attributes.category_name as product_category_name,
		coalesce(sales_30d.sales_amount_30d, 0) as sales_amount_30d,
		coalesce(sales_30d.units_sold_30d, 0) as units_sold_30d,
		coalesce(sales_30d.ticket_count_30d, 0) as ticket_count_30d,
		case
			when coalesce(sales_30d.ticket_count_30d, 0) = 0 then null
			else sales_30d.units_sold_30d / sales_30d.ticket_count_30d::numeric
		end as avg_units_per_ticket_30d,
		case
			when coalesce(sales_30d.ticket_count_30d, 0) = 0 then null
			else sales_30d.sales_amount_30d / sales_30d.ticket_count_30d::numeric
		end as avg_revenue_per_ticket_30d,
		coalesce(sales_30d.units_sold_30d, 0) * coalesce(product_attributes.profit_per_unit_inc_vat, 0) as estimated_gross_profit_30d,
		latest_velocity.current_inventory_qty,
		latest_velocity.sold_qty_7d,
		latest_velocity.sold_qty_30d,
		latest_velocity.days_of_cover_30d,
		latest_velocity.velocity_band,
		latest_velocity.stock_status,
		dense_rank() over (order by coalesce(sales_30d.sales_amount_30d, 0) desc) as sales_rank_30d,
		dense_rank() over (order by coalesce(sales_30d.units_sold_30d, 0) * coalesce(product_attributes.profit_per_unit_inc_vat, 0) desc) as profit_rank_30d,
		dense_rank() over (order by coalesce(latest_velocity.sold_qty_30d, 0) desc) as velocity_rank_30d,
		current_timestamp as dbt_loaded_at,
		'rpt_product_performance_30d' as dbt_source_relation
	from product_attributes
	left join sales_30d
		on product_attributes.item_id = sales_30d.item_id
	left join latest_velocity
		on product_attributes.item_id = latest_velocity.item_id
)

select *
from product_performance
