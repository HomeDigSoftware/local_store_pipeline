{{ config(materialized='table') }}

-- Product master data for inventory and sales analysis
-- Source: Items table (1,950 records identified in data discovery)
-- Note: Column names need to be validated against actual table structure

with source_data as (
    select * from {{ source('store_data', 'items') }}
),

cleaned_items as (
    select
        -- Start with all columns to understand structure
        *,
        current_timestamp as dbt_loaded_at,
        'stg_items' as dbt_source_relation
        
    from source_data
    where item_id is not null
)

select * from cleaned_items

-- TODO: Update column mappings once actual Items table structure is confirmed
-- This initial version uses wildcard (*) to avoid column name errors