
{{
  config(
    materialized = 'table',
    )
}}

SELECT 
    relname AS table_name,
    n_live_tup AS row_count
FROM pg_stat_user_tables
ORDER BY row_count DESC

{# SELECT 
   *
FROM pg_stat_user_tables
ORDER BY row_count DESC #}

