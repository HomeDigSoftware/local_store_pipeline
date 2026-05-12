{% snapshot snap_inventory_balance %}

{{
	config(
		unique_key='item_id',
		strategy='check',
		check_cols=[
			'opening_inventory_qty',
			'inventory_balance_qty',
			'counted_inventory_qty'
		],
		invalidate_hard_deletes=True
	)
}}

select
	item_id,
	opening_inventory_qty,
	inventory_balance_qty,
	counted_inventory_qty,
	product_category_id,
	product_category_name,
	item_name,
	unit_cost,
	unit_cost_inc_vat,
	unit_sale_price,
	profit_per_unit_inc_vat,
	dbt_loaded_at,
	dbt_source_relation
from {{ ref('stg_store_data__inventory') }}

{% endsnapshot %}
