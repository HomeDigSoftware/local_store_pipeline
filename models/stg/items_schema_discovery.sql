{{ config(materialized='view') }}

-- Get column information for Items table
select
    COLUMN_NAME,
    DATA_TYPE,
    IS_NULLABLE,
    CHARACTER_MAXIMUM_LENGTH
from INFORMATION_SCHEMA.COLUMNS 
where TABLE_NAME = 'Items'
  and TABLE_SCHEMA = 'dbo'
order by ORDINAL_POSITION