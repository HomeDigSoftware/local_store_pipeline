{% snapshot snap_items_price_history %}

{{
	config(
		unique_key='item_id',
		strategy='check',
		check_cols=[
			'item_name',
			'item_type_id',
			'cost_per_unit',
			'cost_per_unit_inc_vat',
			'sale_price',
			'profit_per_unit_inc_vat'
		],
		invalidate_hard_deletes=True
	)
}}

select
	item_id,
	item_name,
	item_type_id,
	cost_per_unit,
	cost_per_unit_inc_vat,
	sale_price,
	profit_per_unit_inc_vat,
	dbt_loaded_at,
	dbt_source_relation
from {{ ref('stg_store_data__items') }}

{% endsnapshot %}
