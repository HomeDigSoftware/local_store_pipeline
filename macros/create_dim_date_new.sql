{% macro create_dim_date_new(source_table, date_column, week_start_day='sunday') %}

    {# Step 1: Find the minimum date from the table #}
    {% set min_date_query %}
        select min({{ date_column }}::date) as min_date
        from {{ source_table }}
    {% endset %}
    
    {# Execute the query and get the result #}
    {% set results = run_query(min_date_query) %}
    
    {# Save the minimum date in a variable #}
    {% if execute %}
        {% set start_date = results.columns[0].values()[0] %}
    {% else %}
        {% set start_date = '2000-01-01' %}
    {% endif %}

    {# Step 2: Create date series from minimum date to current date #}
    with recursive date_series as (
        select 
            cast('{{ start_date }}' as date) as date_day
            
        union all
        
        select 
            cast(date_day + interval '1 day' as date)
        from date_series
        where date_day + interval '1 day' <= current_date
    )
    
    {# Step 3: Create all date dimension columns #}
    select
        date_day as date_actual,
        extract(year from date_day) as year,
        extract(month from date_day) as month_number,
        trim(to_char(date_day, 'Month')) as month_name,
        extract(day from date_day) as day_number,
        extract(dow from date_day) as day_of_week_number,
        trim(to_char(date_day, 'Day')) as day_name,
        extract(quarter from date_day) as quarter,

        -- Week start date based on week_start_day parameter
        case 
            when lower('{{ week_start_day }}') = 'sunday' 
                then date_day - extract(dow from date_day) * interval '1 day'
            else 
                date_day - (extract(dow from date_day) - 1) * interval '1 day'
        end as week_start_date,

        -- Week end date
        case 
            when lower('{{ week_start_day }}') = 'sunday'
                then date_day + (6 - extract(dow from date_day)) * interval '1 day'
            else 
                date_day + (7 - (extract(dow from date_day) - 1) - 1) * interval '1 day'
        end as week_end_date,

        -- Mark weekends (Friday and Saturday)
        case 
            when extract(dow from date_day) in (5, 6) then true
            else false
        end as is_weekend,

        to_char(date_day, 'IYYY-IW') as year_week,
        
        '{{ run_started_at.strftime("%Y-%m-%d %H:%M:%S") }}'::timestamp as dbt_run_time

    from date_series

{% endmacro %}