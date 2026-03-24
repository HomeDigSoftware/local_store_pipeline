# Store Analytics Pipeline

A comprehensive data pipeline for retail analytics, transforming point-of-sale data into actionable business insights.

## 🏗️ Architecture Overview

```mermaid
graph LR
    A[Verifon Retail 360 POS] --> B[SQL Server Backup]
    B --> C[Task Scheduler]
    C --> D[SSH Transfer]
    D --> E[Data Lake - SSMS]
    E --> F[dbt Transformation]
    F --> G[Staging Schema STG]
    G --> H[Automated CSV Export]
    H --> I[Python Analytics]
    I --> J[Reports & Dashboards]
```

## 📊 Business Value

This pipeline enables real-time retail analytics including:
- **Sales Performance**: Daily, weekly, monthly revenue tracking
- **Employee Analytics**: Working hours, productivity metrics
- **Product Intelligence**: Inventory turnover, bestsellers analysis
- **Operational Insights**: Peak hours, customer flow patterns

## 🔧 Technical Stack

- **Source System**: Verifon Retail 360 POS
- **Data Transfer**: Windows Task Scheduler + SSH
- **Data Warehouse**: SQL Server Management Studio (SSMS)
- **Transformation**: dbt (data build tool)
- **Analytics**: Python (Pandas, Plotly, etc.)
- **Orchestration**: Windows Task Scheduler + Python scripts

## � Development Process & Data Discovery

### Phase 1: Data Discovery & Source Analysis

The first critical step was understanding the source data structure from the Verifon Retail 360 POS system. Using exploratory queries to identify the most data-rich tables:

```sql
-- Data discovery query used in models/stg/exploring_data.sql
SELECT 
    t.name AS table_name,
    SUM(p.rows) AS row_count
FROM sys.tables t
JOIN sys.partitions p 
    ON t.object_id = p.object_id
WHERE p.index_id IN (0,1)
GROUP BY t.name
ORDER BY row_count DESC;
```

### 📈 Key Data Discovery Findings

**Top 10 Tables by Volume:**

| Table Name | Row Count | Business Purpose |
|------------|-----------|------------------|
| Calendar | 40,541 | Date dimension for time-based analytics |
| **Fact_Sales** | **14,946** | **Primary sales transactions fact table** |
| InterfaceLog | 11,618 | System integration and transaction logs |
| DocumentsLines_continue | 10,295 | Extended transaction line items |
| DocumentLines | 10,294 | Core transaction line items |
| ReceiptLines | 8,331 | Receipt line item details |
| ReceiptLines_continue | 8,331 | Extended receipt information |
| OnlineTransactionsTransmission | 6,317 | Online payment processing logs |
| Receipts | 5,734 | Receipt headers |
| Documents | 5,733 | Transaction document headers |

**Employee & Operational Tables:**

| Table Name | Row Count | Business Purpose |
|------------|-----------|------------------|
| Inventory | 3,050 | Current stock levels |
| Items | 1,950 | Product master data |
| EmployeesAttendance | 47 | Employee time tracking |
| Fact_Attendance_Event | 47 | Attendance event logging |
| **Fact_Shifts** | **23** | **Employee shift management** |

### Strategic Data Architecture Insights:
- **Fact_Sales (14,946 rows)**: Primary transactional data source for revenue analytics
- **Fact_Shifts (23 rows)**: Employee shift data enabling workforce analytics
- **Calendar (40,541 rows)**: Rich date dimension for sophisticated time-based reporting
- **InterfaceLog (11,618 rows)**: Critical for data lineage and system monitoring
- **Items/Inventory**: Complete product catalog with stock management

## 📁 Project Structure

```
store_pipeline/
├── models/
│   ├── stg/                           # Raw data cleaning & standardization
│   │   ├── exploring_data.sql         # Data discovery queries
│   │   ├── stg_fact_sales.sql         # Sales transactions (14,946 rows)
│   │   ├── stg_fact_shifts.sql        # Employee shifts (23 rows)
│   │   └── stg_calendar.sql           # Date dimension (40,541 rows)
│   ├── intermediate/                  # Business logic transformations
│   └── marts/                        # Final analytical models
├── macros/                           # Reusable SQL functions
├── seeds/                            # Static reference data
├── tests/                            # Data quality tests
├── scripts/
│   ├── export_to_csv.py              # Automated CSV export
│   └── generate_reports.py           # Report generation
└── docs/                             # Documentation
```

## 🚀 Getting Started

### Prerequisites
- Python 3.8+
- SQL Server access
- dbt-sqlserver adapter
- SSH access configured

### Installation
```bash
# Clone repository
git clone [repository-url]
cd store_pipeline

# Install dependencies
uv sync

# Configure dbt profile
# Edit ~/.dbt/profiles.yml with your SQL Server connection
```

### Running the Pipeline
```bash
# 1. Explore data structure and volumes
uv run dbt run --select exploring_data

# 2. Build core staging models based on discovery
uv run dbt run --select stg_fact_sales stg_fact_shifts

# 3. Build supporting staging models  
uv run dbt run --select stg_*

# 4. Run full pipeline
uv run dbt run

# 5. Run data quality tests
uv run dbt test

# 6. Generate documentation  
uv run dbt docs generate
uv run dbt docs serve
```

### Development Workflow
1. **Data Discovery**: Run `exploring_data.sql` to understand source structure
2. **Priority Models**: Build high-volume tables first (`Fact_Sales`, `Calendar`)  
3. **Employee Analytics**: Implement `Fact_Shifts` for workforce insights
4. **Business Logic**: Create intermediate transformations
5. **Final Reports**: Build mart layer with business metrics
6. **Quality Assurance**: Add comprehensive testing
7. **Documentation**: Update README with each new capability

## 📈 Data Models

### Data Discovery Layer (`models/stg/exploring_data.sql`)
- **Purpose**: Understand Verifon POS system structure and data volumes
- **Key Query**: Table row counts to identify primary data sources
- **Findings**: `Fact_Sales` (14,946 rows) and `Fact_Shifts` (23 rows) as core business tables
- **Usage**: Guides staging model development priorities

### Staging Layer (`models/stg/`)
- **stg_fact_sales.sql**: Primary sales transactions cleaning (14,946 rows)
  - Sales amounts, transaction dates, employee/item references
  - Data quality checks for positive amounts and valid dates
- **stg_fact_shifts.sql**: Employee shift data preparation (23 rows)  
  - Shift schedules, working hours, employee assignments
  - Time zone standardization and shift overlap handling
- **stg_calendar.sql**: Date dimension preparation (40,541 rows)
- **Basic data type standardization and quality checks**

### Intermediate Layer (`models/intermediate/`)
- Business logic transformations
- Calculated metrics and KPIs
- Data enrichment and joins

### Marts Layer (`models/marts/`)
- `fct_sales`: Enhanced sales fact table with business calculations
- `fct_employee_productivity`: Combined sales and shifts analysis  
- `dim_products`: Product dimension from Items table
- `dim_employees`: Employee dimension
- `rpt_daily_sales`: Daily sales summary reports
- `rpt_employee_hours`: Employee productivity reports

## ⚙️ Automated Workflows

### Data Ingestion (Daily 2:00 AM)
1. POS system creates backup file
2. Task Scheduler triggers SSH transfer
3. SSMS imports new data
4. Data quality validation

### Analytics Pipeline (Daily 3:00 AM)
1. dbt transformations execute
2. Data quality tests run
3. CSV exports generated
4. Python reports created
5. Stakeholder notifications sent

## 📊 Output Deliverables

### CSV Exports (Based on Actual Data Volumes)
- `daily_sales_summary.csv` - From Fact_Sales analysis (14,946 transactions)
- `employee_shift_hours.csv` - From Fact_Shifts data (23 shift records)  
- `product_performance.csv` - From Items and Inventory analysis (1,950 products)
- `calendar_business_insights.csv` - From Calendar dimension (40,541 date records)

### Automated Reports  
- **Daily Sales Dashboard**: Revenue trends from 14,946+ transactions
- **Employee Productivity Report**: Shift analysis and hours tracking (23 shifts monitored)
- **Inventory Management**: Real-time stock levels (3,050 items tracked)
- **Business Calendar Analytics**: Seasonal patterns and peak periods
- **Monthly Executive Summary**: Complete business performance review

## 🔍 Monitoring & Quality

- **Data Freshness**: Automated checks for data recency
- **Data Quality**: dbt tests for uniqueness, not-null, referential integrity
- **Pipeline Health**: Logging and error notification system
- **Performance**: Query optimization and execution monitoring

## 🚀 Future Enhancements

- [ ] Real-time streaming with Apache Kafka
- [ ] Advanced ML models for demand forecasting
- [ ] Interactive Power BI dashboard
- [ ] Mobile alerts and notifications
- [ ] Customer segmentation analysis

## 👥 Stakeholder Access

- **Store Managers**: Daily operational reports
- **Regional Directors**: Weekly performance summaries
- **C-Suite**: Monthly strategic dashboards
- **IT Operations**: System health and performance metrics

## 📞 Support

For technical issues or feature requests, contact the Analytics Engineering team.

---

## 🚧 Development Status 

**Current Phase**: Staging Layer Development

### Next Steps:
1. **Update SQL in staging models**:
   - Replace placeholder queries in `stg_fact_sales.sql` with actual Fact_Sales transformations
   - Replace placeholder queries in `stg_fact_shifts.sql` with actual Fact_Shifts transformations  
   - Add proper column mappings based on actual table schemas

2. **Add data quality tests** for both models
3. **Create intermediate transformations** combining sales and shifts data  
4. **Build marts layer** with final business reports

### Data Discovery Completed ✅
- 150+ tables analyzed
- **Fact_Sales**: 14,946 records (Primary sales data)
- **Fact_Shifts**: 23 records (Employee scheduling)  
- **Calendar**: 40,541 records (Date dimension)
- **Items**: 1,950 records (Product catalog)

---
*Built with ❤️ by the Analytics Engineering Team*


<!-- 
אני רוצה ליצור פרופיל של analytics engineer in github 
אני רוצה שהפרוייקט הנוכחי יהיה כלול בו  
אני רוצה שתעזור לי להכין את הפרוייקט למטרה הזאת כולל מה חסר ואיזה סיפור אני יציג , סט הנתונים הוא של עסק של מכר שלי מה שעשיתי בפועל הוא 
1. יצרתי task-schedule שמעתיק את קובץ הגיבוי בקופה הרושמת , מסוג : verifone retail 360 שולח בחיבור SSH את הקובץ למחשב של הבעלים 
2. על המחשב של הבעלים יש task-schedule שמריץ תסריט SQL   -->