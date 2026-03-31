{{ config(materialized='table') }}

-- Quick exploration of Items table structure
-- This will help us understand the actual column names

select *
from {{ source('store_data', 'items') }}
limit 5