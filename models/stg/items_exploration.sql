{{ config(materialized='view') }}

-- Quick exploration of Items table structure
-- This will help us understand the actual column names

select top 5 *
from {{ source('store_data', 'Items') }}