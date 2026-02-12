# Copilot Instructions for store_pipeline

## Project Overview
This is a **dbt (data build tool) project** named `store_pipeline`, managing data transformation workflows for a store analytics pipeline. dbt compiles SQL models into executable SQL and orchestrates their execution order based on dependencies.

## Architecture & Key Concepts

### dbt Project Structure
- **models/**: SQL/Jinja templates defining data transformations. Each model becomes a table/view in the data warehouse
  - Currently uses `example/` subdirectory with starter models
  - Models reference each other via `{{ ref('model_name') }}` for dependency management
- **seeds/**: CSV files loaded as tables (currently empty, ready for static data)
- **macros/**: Reusable Jinja functions (currently empty, ready for custom SQL logic)
- **tests/**: Data quality tests (currently empty)
- **snapshots/**: SCD Type 2 implementations for tracking historical changes
- **target/**: Compiled SQL and metadata (gitignored build artifacts)

### Configuration Files
- **dbt_project.yml**: Project-level config defining project name (`store_pipeline`), paths, and model materializations
  - Default materialization for `example/` models: `view`
  - Models can override this with `{{ config(materialized='table') }}` in-file
- **profiles.yml**: Database connection config (NOT in repo - lives in `~/.dbt/` on Windows)
  - Profile name: `store_pipeline` (matches `dbt_project.yml`)

### Model Patterns (from existing examples)
- **Inline config**: Use `{{ config(materialized='table') }}` at top of SQL files to override project defaults
- **CTEs for staging**: Use `with source_data as (...)` pattern for intermediate transformations
- **Model dependencies**: Reference upstream models with `{{ ref('my_first_dbt_model') }}` not direct table names
- **schema.yml**: Define model documentation and data tests alongside models
  - Tests: `unique`, `not_null`, custom tests
  - Document all columns with descriptions

## Critical Workflows

### Running the Project
```bash
# Execute this with uv (Python package manager wrapper used in this project)
uv run dbt run        # Build all models
uv run dbt test       # Run data quality tests
uv run dbt build      # Run + test in dependency order
uv run dbt compile    # Generate SQL without executing
```

**Important**: This project uses `uv run` prefix for dbt commands (not plain `dbt`), indicating uv manages the Python environment.

### Development Workflow
1. Create/modify SQL models in `models/`
2. Add tests and documentation in `schema.yml` files
3. Run `uv run dbt run --select model_name` to test individual model
4. Run `uv run dbt test` to validate data quality
5. Compiled SQL appears in `target/compiled/` for debugging

### Adding New Models
1. Create `.sql` file in appropriate `models/` subdirectory
2. Use `{{ ref() }}` for dependencies, never hardcode table names
3. Add entry in `schema.yml` with description and tests
4. Configure materialization strategy (`view` for development, `table` for production, `incremental` for large datasets)

## Project-Specific Conventions

### Materialization Strategy
- **Views** (current default for `example/`): Fast builds, always fresh data, slower queries
- **Tables**: Slower builds, faster queries, manual refresh needed
- **Override** project defaults inline: `{{ config(materialized='table') }}`

### Testing Approach
- Define tests in `schema.yml` under model columns
- Use built-in tests: `unique`, `not_null`, `accepted_values`, `relationships`
- Custom tests go in `tests/` directory

### Naming Conventions (to establish as project grows)
- Models should follow `staging_`, `intermediate_`, `fact_`, `dim_` prefixes as layers emerge
- Source files reference raw data, models transform it

## Common Pitfalls
- **Don't hardcode table names**: Always use `{{ ref('model_name') }}` for dbt dependency tracking
- **Profile location**: `profiles.yml` is NOT in project directory (it's in `~/.dbt/profiles.yml` on Windows)
- **Target directory**: Never edit files in `target/` - these are generated artifacts
- **Run command**: Use `uv run dbt [command]` not plain `dbt [command]`

## Next Steps for This Codebase
- Replace `example/` starter models with actual store pipeline models
- Add source definitions in `models/sources.yml` for raw data tables
- Implement proper staging → intermediate → marts layer structure
- Add seeds for reference data (product categories, store locations, etc.)
- Create custom macros for reusable transformations
