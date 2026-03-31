{{ create_dim_date_new(
    source_table=source('store_data', 'documents'),
    date_column='recordingdate',
    week_start_day='sunday'
) }}

