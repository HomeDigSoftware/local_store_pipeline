{{ config(materialized='table') }}

with employees as (
	select *
	from {{ ref('stg_store_data__employees') }}
),

dim_employee as (
	select
		md5(coalesce(employee_id::text, '')) as employee_key,
		employee_id,
		employee_name,
		current_timestamp as dbt_loaded_at,
		'dim_employee' as dbt_source_relation
	from employees
)

select *
from dim_employee
