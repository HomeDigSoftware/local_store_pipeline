{{ config(materialized='table') }}

with sales as (
	select
		receipt_date,
		payment_type,
		is_credit,
		document_id,
		quantity,
		net_sales_amount
	from {{ ref('fct_sales') }}
	where is_return = 0
),

by_payment as (
	select
		receipt_date,
		payment_type,
		is_credit,
		sum(net_sales_amount) as sales_amount,
		count(distinct document_id) as ticket_count,
		sum(quantity) as units_sold
	from sales
	group by receipt_date, payment_type, is_credit
),

payment_mix as (
	select
		receipt_date,
		payment_type,
		is_credit,
		sales_amount,
		ticket_count,
		units_sold,
		round(
			sales_amount / nullif(sum(sales_amount) over (partition by receipt_date), 0) * 100,
			2
		) as payment_sales_share,
		round(
			ticket_count::numeric / nullif(sum(ticket_count) over (partition by receipt_date), 0) * 100,
			2
		) as payment_ticket_share,
		current_timestamp as dbt_loaded_at,
		'rpt_payment_mix_daily' as dbt_source_relation
	from by_payment
)

select *
from payment_mix
