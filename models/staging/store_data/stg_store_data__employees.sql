{{ config(materialized='table') }}

with source_data as (
	select *
	from {{ source('store_data', 'employeesselection_byentrance') }}
),

cleaned_employees as (
	select
		emplyeenumber as employee_id,
		longname as employee_name,
		current_timestamp as dbt_loaded_at,
		'stg_store_data__employees' as dbt_source_relation
	from source_data
	where emplyeenumber is not null
)

select *
from cleaned_employees
