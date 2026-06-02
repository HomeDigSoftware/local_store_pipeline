# Pipeline Scripts — Documentation

## Daily Execution Order

```
01_restore_backup.py
       ↓
02_extract_load.py
   ├── generate_synthetic_invoices.py  (called automatically from 02)
   └── → saves updated .bak backup
       ↓
03_load_to_supabase.py  (optional)
       ↓
dbt run
       ↓
dbt test
```

---

## 01_restore_backup.py

**Purpose:** Restores the `.bak` backup file into SQL Server before daily processing begins.

### Configuration

| Constant | Value |
|----------|-------|
| `SERVER` | `DESKTOP-E7P613O\STORE_DATA` |
| `DATABASE` | `POS_SANDBOX` |
| `USER` / `PASSWORD` | tzaf / 240683 |
| `BACKUP_FILE` | Fixed path to the `.bak` file |

### Functions

#### `restore_database()`
- Verifies the `.bak` file exists on disk
- Runs `sqlcmd` with `RESTORE DATABASE [...] FROM DISK='...' WITH REPLACE, RECOVERY;`
- If `sqlcmd` returns a non-zero exit code — exits with `sys.exit(1)`
- Writes logs to `pipeline.log` and stdout

---

## 02_extract_load.py

**Purpose:** Generates synthetic invoices in SQL Server, copies all tables to local Postgres, and saves a new `.bak` backup so the next day's restore includes today's synthetic data.

### Configuration

| Constant | Description |
|----------|-------------|
| `MSSQL_CONN_STR` | ODBC connection string to SQL Server |
| `PG_URL` | Local Postgres connection (`store_local`) |
| `PG_SCHEMA` | `raw` |
| `SKIP_TABLES` | Tables/views to exclude from loading |
| `MSSQL_SERVER/DATABASE/USER/PASSWORD` | SQL Server credentials used for backup |
| `BACKUP_FILE` | Path to the `.bak` file — overwritten at the end of each run |
| `ENABLE_SYNTHETIC_INVOICES` | `True` — set to `False` to disable generation |
| `SYNTHETIC_INVOICE_COUNT` | Base invoice count before daily profile adjustment (35) |
| `SYNTHETIC_MIN/MAX_LINES` | Line count range per invoice (1–5) |
| `SYNTHETIC_CREDIT_RATE` | Probability of credit card payment (0.22) |
| `SYNTHETIC_RETURN_RATE` | Probability of a return invoice (0.03) |
| `SYNTHETIC_DISCOUNT_RATE` | Probability of a line discount (0.17) |
| `SYNTHETIC_UPDATE_INVENTORY` | Whether to update `dbo.Inventory` balances (True) |
| `SYNTHETIC_SEED` | Random seed for reproducibility (42) |

### Functions

#### `run_synthetic_generation()`
1. Skips if `ENABLE_SYNTHETIC_INVOICES = False`
2. Queries `SELECT MAX(DocumentDate) FROM dbo.Documents` to determine the target date: **one day after the latest existing date** — keeps the data timeline continuous
3. Falls back to `date.today()` if the query fails
4. Builds a `subprocess` command that runs `generate_synthetic_invoices.py --commit` with all configured parameters
5. Streams the generator's output to the log file

#### `extract_and_load()`
1. Calls `run_synthetic_generation()` so new synthetic rows are in SQL Server before copying
2. Connects to SQL Server and discovers all `BASE TABLE` objects in `dbo`
3. For each table not in `SKIP_TABLES`: reads it into a DataFrame and writes to Postgres (`if_exists="replace"`)
4. Lowercases all column names before writing to Postgres
5. Logs any tables that were skipped due to errors

#### `save_backup()`
1. Ensures the target directory exists
2. Runs `sqlcmd` with `BACKUP DATABASE [...] TO DISK=N'...' WITH FORMAT, INIT, COMPRESSION, STATS=10;`
3. **Overwrites** the same `.bak` file — so tomorrow's `01_restore_backup.py` restores a state that includes today's synthetic invoices
4. Raises `RuntimeError` if `sqlcmd` returns a non-zero exit code

### `__main__`
```python
extract_and_load()
save_backup()
```

---

## generate_synthetic_invoices.py

**Purpose:** Inserts synthetic POS invoices directly into the SQL Server source tables, with a different demand profile for each day of the week.

### Tables Written To
- `dbo.Documents` — invoice header
- `dbo.DocumentLines` — line items
- `dbo.ReceiptLines` — payment details
- `dbo.Inventory` — stock balance updates (only if `--update-inventory`)

### Default behavior: dry-run — add `--commit` to persist changes

### CLI Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--date` | MAX(DocumentDate)+1 | Business date for generated invoices (YYYY-MM-DD) |
| `--invoice-count` | 30 | Base number of invoices (before daily profile adjustment) |
| `--min-lines` | 1 | Minimum lines per invoice |
| `--max-lines` | 5 | Maximum lines per invoice |
| `--credit-rate` | 0.20 | Probability of credit card payment (type 3) |
| `--return-rate` | 0.03 | Probability that an invoice is a return (negative totals) |
| `--discount-rate` | 0.15 | Probability that a line receives a random discount |
| `--update-inventory` | False | Apply inventory balance updates in `dbo.Inventory` |
| `--seed` | None | Random seed for reproducible output |
| `--commit` | False | Persist inserts — without this flag changes are rolled back |

### Classes / Dataclasses

#### `ItemRecord`
Represents one item from the active item pool. Fields: `item_id`, `item_name`, `sale_price`, `inventory_balance`, `popularity_weight`.

#### `DayDemandProfile`
Daily demand profile. Fields: `name`, `invoice_multiplier`, `credit_rate_multiplier`, `return_rate_multiplier`, `discount_rate_multiplier`, `hourly_windows` (time windows with probability weights).

#### `WEEKDAY_PROFILES`
Dictionary `{0: DayDemandProfile, ..., 6: DayDemandProfile}` — one per day of week (0=Monday, 6=Sunday). Friday is the busiest (×1.22), Saturday is the slowest (×0.72), Sunday is high (×1.15).

### Functions

#### `parse_args()`
Parses and validates all CLI arguments; raises explicit errors for out-of-range values.

#### `quantize_money(value)` / `quantize_qty(value)`
Rounds monetary values to 2 decimal places / quantities to 3 decimal places.

#### `to_source_date(target_date)`
Converts a `date` object to `YYYYMMDD` string format used in `DocumentDate` in SQL Server.

#### `resolve_day_profile(target_date)`
Returns the `DayDemandProfile` matching the weekday of `target_date`.

#### `adjusted_rate(base_rate, multiplier)`
Multiplies `base_rate` by `multiplier`, clamped to [0, 1].

#### `adjusted_invoice_count(base_invoice_count, target_date, rng)`
Calculates how many invoices to generate: `base × profile.invoice_multiplier × jitter(0.92–1.08)`, minimum 1.

#### `fetchone_dict(cursor, query, params)` / `fetchall_dicts(cursor, query, params)`
pyodbc wrappers that return `dict` / `list[dict]` instead of raw tuples.

#### `fetch_template_row(cursor, table_name, where_clause)`
Fetches a single row from a table to use as a template — taken from the highest-ordered row. Used to copy column values that are not explicitly computed.

#### `build_item_pool(cursor)`
Queries `Items` + `Inventory` + sales history (`DocumentLines`). Returns a list of `ItemRecord` with a `popularity_weight` combining historical frequency and current stock. Filters: `Card_ID=11`, `CardsGroup=3`, price > 0, inventory > 0.

#### `choose_sale_time_seconds(rng, profile)`
Picks a random time based on the day profile's `hourly_windows`. Returns the number of seconds from midnight.

#### `choose_line_count(rng, min_lines, max_lines)`
Picks the number of lines per invoice with an inverse weight (fewer lines are more likely).

#### `choose_quantity(rng, available_inventory)`
Picks item quantity (1–4) with exponential weighting. Caps at available inventory.

#### `choose_items(rng, item_pool, requested_lines, inventory_tracker)`
Selects items for an invoice by `popularity_weight`, without duplicates, and only from items with inventory >= 1.

#### `next_identity_values(cursor)`
Returns `MAX(Document_ID) + 1` as the starting ID for the current run's invoice sequence.

#### `build_insert_sql(table_name, column_names)`
Builds an `INSERT INTO dbo.[...] (col1, col2, ...) VALUES (?, ?, ...)` string.

#### `insert_row(cursor, table_name, row_values)`
Filters out identity columns (`s__sequence`) and executes the INSERT. Identity columns are excluded so SQL Server auto-generates them.

#### `update_inventory_row(cursor, item_id, quantity_delta)`
Executes `UPDATE dbo.Inventory SET InventoryBalance = InventoryBalance + delta` for the given item, filtered by `Card_ID=11, CardsGroup=3`.

#### `main()`
Main logic:
1. `parse_args()` + `build_item_pool()` + fetch template rows
2. Loop over `planned_invoice_count`:
   - Determines `is_return` (negative totals) and `payment_type` (1=cash / 3=credit)
   - Builds a `Documents` row from the template with computed values
   - Inner loop over lines: selects items, computes price, discount, quantity
   - Appends a `ReceiptLines` row with the invoice total
   - Updates `inventory_tracker` in memory and optionally `dbo.Inventory`
3. `COMMIT` if `--commit`, otherwise `ROLLBACK`
4. Prints a summary: invoice count, line count, total revenue, cash/credit split, returns count

---

## 03_load_to_supabase.py

**Purpose:** Pushes all tables from local Postgres (`raw` schema) to Supabase (production layer).

### Configuration

| Constant | Value |
|----------|-------|
| `LOCAL_PG_URL` | `postgresql://postgres:...@localhost:5432/store_local` |
| `SUPABASE_URL` | Supabase connection string |
| `SOURCE_SCHEMA` / `TARGET_SCHEMA` | `raw` / `raw` |

### Functions

#### `load_to_supabase()`
1. Connects to both databases
2. Creates the `raw` schema in Supabase if it does not exist
3. Discovers all `BASE TABLE` objects in the local `raw` schema
4. For each table: reads into a DataFrame and uploads to Supabase (`if_exists="replace"`)
5. Logs a summary of any skipped tables

---

## Shared Log File

All scripts write to `scripts/pipeline.log` (UTF-8, append mode) and to stdout simultaneously.

Format: `YYYY-MM-DD HH:MM:SS [LEVEL] message`
