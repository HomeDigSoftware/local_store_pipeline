# Store Analytics Pipeline

An end-to-end retail analytics platform that turns a small optical store's
point-of-sale data into a live business dashboard. Real POS history is augmented
with realistic synthetic sales, modelled with **dbt**, served from **Supabase**,
and visualised by a **Next.js** dashboard — refreshed automatically every night.

> **Portfolio project** demonstrating analytics-engineering practice: layered dbt
> modelling, data-quality testing, SCD snapshots, an inventory time-series, and a
> fully automated load → transform → publish → cache-bust pipeline.

---

## Architecture

```
┌─────────────────────┐
│  Verifone Retail360  │   real POS backup (.bak)
│      SQL Server      │
└──────────┬───────────┘
           │  01_restore_backup.py  (RESTORE .bak)
           ▼
┌──────────────────────────────────────────────┐
│  Python ingestion  (scripts/, the "EL")       │
│  02_extract_load_03.py                         │
│   • SQL Server → local Postgres (raw)          │
│   • + synthetic invoices (Option C variance)   │
│   • + periodic inventory replenishment (~6d)   │
└──────────┬─────────────────────────────────────┘
           ▼
┌─────────────────────┐     03_load_to_supabase_allowlist.py
│  Local Postgres      │ ──────────────────────────────────► ┌──────────────────┐
│  db: store_local     │     8 source tables (TRUNCATE+append) │  Supabase (raw)  │
│  schema: raw         │                                       └────────┬─────────┘
└──────────┬───────────┘                                                │
           │  dbt (the "T")                                             │
           ▼                                                            ▼
   staging → intermediate → marts/core → marts/reporting     dbt run --target prod
           │                                                            │
           ▼                                                            ▼
   local raw (dev: all layers)                          ┌──────────────────────────┐
                                                         │ Supabase store_pipeline   │
                                                         │  dim_*, fct_*, rpt_*      │
                                                         └────────────┬──────────────┘
                                                                      │ revalidate webhook
                                                                      ▼
                                                         ┌──────────────────────────┐
                                                         │  Next.js dashboard (Vercel)│
                                                         └──────────────────────────┘
```

**Two pipelines, EL then T:** Python scripts do the Extract+Load (dbt does *not*
load raw data); dbt does the Transform. See [CLAUDE.md](CLAUDE.md) for the full
architecture and conventions, and [INVOICE_GENERATION_WORKFLOW.md](INVOICE_GENERATION_WORKFLOW.md)
for the synthetic-invoice + replenishment logic.

---

## Tech stack

| Layer | Technology |
|-------|------------|
| Source | Verifone Retail 360 POS → SQL Server `.bak` |
| Ingestion / EL | Python (pandas, SQLAlchemy, pyodbc), orchestrated by `uv` |
| Transform / T | **dbt 1.11.3**, postgres adapter (`dbt_utils`, `dbt_expectations`) |
| Dev warehouse | local **Postgres** (`store_local`, schema `raw`) |
| Prod warehouse | **Supabase** Postgres (schema `store_pipeline`) |
| Dashboard | Next.js on Vercel (ISR + `revalidate` webhook) |
| Automation | Windows Task Scheduler → `run_daily_backfill.bat` |

Everything runs through **`uv`**: `uv run dbt ...`, `uv run python ...`.

---

## dbt project layout

```
models/
  staging/store_data/    stg_store_data__*      one per source table; clean + rename only
  intermediate/
    sales/               int_sales__*           line items, daily product/store, returns, attribution
    inventory/           int_inventory__*       current stock, velocity, stock health
    workforce/           int_workforce__*       attendance → shifts → daily hours
  marts/
    core/                dim_*, fct_*            conformed dims + facts (incl. fct_inventory_snapshot_history)
    reporting/           rpt_*                   13 dashboard tables (the prod surface)
snapshots/               2 SCD snapshots         item price history, inventory balance
macros/                  create_dim_date_new.sql recursive date-spine → dim_date
```

**Scale:** ~39 models · 179 data tests (0 errors) · 13 `rpt_*` reporting tables ·
2 snapshots · 3 exposures. All models materialised as **table**.

### Reporting tables (`rpt_*`, served to the dashboard)
`rpt_daily_sales` · `rpt_sales_trend_daily` · `rpt_executive_summary_daily` ·
`rpt_sales_by_hour` · `rpt_payment_mix_daily` · `rpt_returns_analysis_daily` ·
`rpt_product_performance_30d` · `rpt_category_performance_30d` ·
`rpt_product_velocity` · `rpt_inventory_risk` · `rpt_inventory_actions` ·
`rpt_inventory_health_trend` · `rpt_employee_productivity`.

---

## Highlights

- **Realistic synthetic data (Option C variance).** Real POS history is short, so
  the pipeline augments it: weekday profile, compound trend, lognormal jitter,
  Israeli payroll calendar, surprise events, and a deterministic inventory
  replenishment cycle (~every 6 days). Date-seeded so the series is reproducible.
- **Inventory time-series.** `fct_inventory_snapshot_history` accumulates one
  point-in-time-correct inventory snapshot per business day (built day-by-day by
  the backfill loop), enabling a real trend report (`rpt_inventory_health_trend`)
  that a single-day snapshot could never support.
- **Data quality.** 179 tests across all layers — `not_null`/`unique`/`relationships`/
  `accepted_values`/`accepted_range`, composite-grain uniqueness, and singular
  cross-model consistency tests. `severity: warn` marks known source noise;
  `error` is reserved for real integrity violations. Map: [DATA_TESTS_CATALOG.md](DATA_TESTS_CATALOG.md).
- **Free-tier-safe delivery.** Supabase `raw` holds only 8 source tables, loaded
  TRUNCATE+append (zero DDL) to avoid PostgREST schema-reload IO storms; the
  inventory history is delivered append-delta so Supabase is a durable archive.

---

## Automation

The whole pipeline runs unattended once a day.

```
Windows Task Scheduler (daily 03:00, wakes from sleep)
        │
        ▼
scripts/run_daily_backfill.bat        (sets PYTHONUTF8=1, logs to scripts/logs/)
        │
        ▼
full_auto_backfill.py --auto-run      (no prompt; safe no-op if already current)
   for each business day D:
     02_extract_load_03.py            → load D into local raw (+ synthetic + replenish)
     dbt run +fct_inventory_snapshot_history --vars snapshot_date=D
   then (once):
     03_load_to_supabase_allowlist.py → 8 sources → Supabase raw
     copy inventory history (append-delta) → Supabase store_pipeline
     dbt run --target prod            → build dim/fct/rpt in store_pipeline
     revalidate_website.py            → bust the dashboard cache
```

`--auto-run` exits cleanly when the data is already up to date, so the daily
schedule is a safe no-op on days with nothing new.

---

## Running it

```bash
# one-time
uv sync
uv run dbt deps

# build / test (dev = local Postgres, schema raw)
uv run dbt run
uv run dbt test

# deploy dashboard models to Supabase
uv run dbt run  --target prod
uv run dbt test --target prod

# backfill manually
uv run python scripts/full_auto_backfill.py            # interactive (prompts for days)
uv run python scripts/full_auto_backfill.py --auto-run # unattended, run until today
uv run python scripts/full_auto_backfill.py --days 1   # smoke test: one day end-to-end
```

Profiles live in `~/.dbt/profiles.yml` (`store_pipeline`: `dev` local Postgres,
`prod` Supabase). Secrets are read from `.env` (gitignored).

---

## Current state (2026-06-16)

- ✅ dbt: 39 models, 179 tests, 0 errors; 13 `rpt_*` deployed to Supabase `store_pipeline`.
- ✅ Disk-IO crisis resolved (raw 539 → 8 tables, indexes, allowlist loader, caching + webhook).
- ✅ Inventory snapshot history + trend report live; append-delta delivery.
- ✅ Daily automated job live — Task Scheduler runs `--auto-run` at 03:00 (wakes from sleep).
- ✅ Prod data backfilled up to date.

Remaining polish is tracked in the dated `WORK_PLAN_*.md` (open tasks) and the
day-by-day history in [WORK_LOG.md](WORK_LOG.md).

---

## Documentation map

| File | Purpose |
|------|---------|
| [CLAUDE.md](CLAUDE.md) | Architecture, stack reality, conventions, commands (source of truth) |
| [WORK_LOG.md](WORK_LOG.md) | Chronological log of completed work |
| `WORK_PLAN_<date>.md` | Remaining open tasks (latest dated file) |
| [DATA_TESTS_CATALOG.md](DATA_TESTS_CATALOG.md) | Living map of every table/column and its tests |
| [INVOICE_GENERATION_WORKFLOW.md](INVOICE_GENERATION_WORKFLOW.md) | Synthetic invoices + inventory replenishment logic |

*(Planning/status docs are kept local-only by convention; the tracked repo is the
dbt project + `scripts/`.)*
