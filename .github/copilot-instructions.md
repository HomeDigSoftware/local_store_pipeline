# Copilot Instructions for store_pipeline

## Project Overview
This is a **retail analytics pipeline project** built with dbt (data build tool), designed for processing real POS (Point of Sale) data from Verifon Retail 360 systems. The pipeline transforms raw transaction data into business intelligence reports for store management, including sales analysis, employee productivity, and inventory insights.

## Business Context
This project serves as a portfolio piece demonstrating end-to-end data engineering capabilities:
- **Data Source**: Real store POS data from Verifon Retail 360
- **Business Value**: Automated daily reports for store managers, regional directors, and executives
- **Technical Challenge**: Complete automation from data extraction to report delivery
- **End Users**: Store managers, regional staff, C-suite executives

## Architecture & Data Flow

### Complete Pipeline Overview
1. **Verifon Retail 360** → Daily backup files
2. **Task Scheduler** → Automated SSH transfer to processing server
3. **SSMS (SQL Server)** → Raw data storage
4. **dbt transformations** → Data cleaning and business logic
5. **Automated CSV exports** → Staging for analytics
6. **Python scripts** → Report generation and dashboards
7. **Email delivery** → Stakeholder notifications

### dbt Project Structure
- **models/stg/**: Staging layer - raw data cleaning and standardization from POS systems
  - Clean transaction data, standardize formats, basic quality checks
- **models/intermediate/**: Business logic transformations
  - Calculate derived metrics, join dimensions, prepare for reporting
- **models/marts/**: Final analytical models for business consumption
  - `fct_sales`: Sales transactions fact table
  - `dim_products`: Product dimension with categories and attributes
  - `dim_employees`: Employee dimension with roles and schedules
  - `rpt_*`: Ready-to-use report tables
- **seeds/**: Static reference data (product categories, store locations, employee roles)
- **macros/**: Reusable SQL functions for retail calculations (margins, seasonality, etc.)
- **tests/**: Data quality tests ensuring business rule compliance
- **snapshots/**: Historical tracking for price changes, product updates

### Configuration Files
- **dbt_project.yml**: Project config with retail-specific materializations
  - Staging: `view` (fast development)  
  - Marts: `table` (fast queries for reports)
  - Reports: `table` with post-hooks for CSV export
- **profiles.yml**: SQL Server connection (lives in `~/.dbt/profiles.yml`)
  - Profile name: `store_pipeline`

## Model Patterns for Retail Analytics

### Staging Models (stg_*)
````sql
{{ config(materialized='view') }}

with source_data as (
    select * from InterfaceLog  -- Raw POS data
),

cleaned as (
    select
        cast(trans_date as date) as transaction_date,
        cast(amount as decimal(10,2)) as sale_amount,
        -- Standard retail transformations
    from source_data
)

select * from cleaned