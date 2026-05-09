{{ config(materialized='table') }}

with current_stock as (
	select *
	from {{ ref('int_inventory__current_stock') }}
),

line_items as (
	select *
	from {{ ref('int_sales__line_items') }}
),

anchor_date as (
	select max(receipt_date) as as_of_date
	from line_items
),

sales_windows as (
	select
		line_items.item_id,
		sum(
			case
				when line_items.is_return = 0
				 and line_items.receipt_date > anchor_date.as_of_date - interval '7 days'
				 and line_items.receipt_date <= anchor_date.as_of_date
					then line_items.quantity
				else 0
			end
		) as sold_qty_7d,
		sum(
			case
				when line_items.is_return = 0
				 and line_items.receipt_date > anchor_date.as_of_date - interval '30 days'
				 and line_items.receipt_date <= anchor_date.as_of_date
					then line_items.quantity
				else 0
			end
		) as sold_qty_30d
	from line_items
	cross join anchor_date
	group by line_items.item_id
),

product_velocity as (
	select
		current_stock.item_id,
		current_stock.item_name,
		current_stock.product_category_id,
		current_stock.product_category_name,
		current_stock.current_inventory_qty,
		coalesce(sales_windows.sold_qty_7d, 0) as sold_qty_7d,
		coalesce(sales_windows.sold_qty_30d, 0) as sold_qty_30d,
		coalesce(sales_windows.sold_qty_30d, 0) / 30.0 as avg_daily_sales_30d,
		case
			when current_stock.current_inventory_qty > 0
				then coalesce(sales_windows.sold_qty_30d, 0) / nullif(current_stock.current_inventory_qty, 0)
			else null
		end as sales_inventory_ratio_30d,
		case
			when coalesce(sales_windows.sold_qty_30d, 0) > 0
				then current_stock.current_inventory_qty / nullif(coalesce(sales_windows.sold_qty_30d, 0) / 30.0, 0)
			else null
		end as days_of_cover_30d,
		case
			when current_stock.current_inventory_qty <= 0 then 'OUT_OF_STOCK'
			when coalesce(sales_windows.sold_qty_30d, 0) = 0 then 'NO_RECENT_SALES'
			when (coalesce(sales_windows.sold_qty_30d, 0) / 30.0) >= 3 then 'FAST'
			when (coalesce(sales_windows.sold_qty_30d, 0) / 30.0) >= 1 then 'STEADY'
			else 'SLOW'
		end as velocity_band,
		current_timestamp as dbt_loaded_at,
		'int_inventory__product_velocity' as dbt_source_relation
	from current_stock
	left join sales_windows
		on current_stock.item_id = sales_windows.item_id
)

select *
from product_velocity
