{{ config(materialized='table') }}

with product_performance as (
	select *
	from {{ ref('rpt_product_performance_30d') }}
),

latest_actions as (
	select *
	from {{ ref('rpt_inventory_actions') }}
	where snapshot_date = (select max(snapshot_date) from {{ ref('rpt_inventory_actions') }})
),

category_sales as (
	select
		product_category_id,
		product_category_name,
		sum(sales_amount_30d) as sales_amount_30d,
		sum(units_sold_30d) as units_sold_30d,
		sum(ticket_count_30d) as ticket_count_30d,
		sum(estimated_gross_profit_30d) as estimated_gross_profit_30d
	from product_performance
	where product_category_id is not null
	group by product_category_id, product_category_name
),

category_inventory as (
	select
		p.product_category_id,
		p.category_name as product_category_name,
		avg(a.days_of_cover_30d) as avg_days_of_cover_30d,
		count(case when a.stock_status = 'OUT_OF_STOCK' then 1 end) as out_of_stock_count,
		count(case when a.stock_status = 'STOCKOUT_RISK' then 1 end) as stockout_risk_count,
		count(case when a.stock_status = 'DEAD_STOCK' then 1 end) as dead_stock_count,
		count(case when a.stock_status = 'OVERSTOCK' then 1 end) as overstock_count
	from latest_actions a
	left join {{ ref('dim_product') }} p
		on a.item_id = p.item_id
	group by p.product_category_id, p.category_name
),

category_performance as (
	select
		cs.product_category_id,
		cs.product_category_name,
		cs.sales_amount_30d,
		cs.units_sold_30d,
		cs.ticket_count_30d,
		cs.estimated_gross_profit_30d,
		coalesce(ci.avg_days_of_cover_30d, 0) as avg_days_of_cover_30d,
		coalesce(ci.out_of_stock_count, 0) as out_of_stock_count,
		coalesce(ci.stockout_risk_count, 0) as stockout_risk_count,
		coalesce(ci.dead_stock_count, 0) as dead_stock_count,
		coalesce(ci.overstock_count, 0) as overstock_count,
		dense_rank() over (order by cs.sales_amount_30d desc) as category_sales_rank_30d,
		dense_rank() over (order by cs.estimated_gross_profit_30d desc) as category_profit_rank_30d,
		current_timestamp as dbt_loaded_at,
		'rpt_category_performance_30d' as dbt_source_relation
	from category_sales cs
	left join category_inventory ci
		on cs.product_category_id = ci.product_category_id
)

select *
from category_performance
