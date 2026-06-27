# 🏪 Convenience Store Analytics Platform

> An end-to-end analytics engineering project: real point-of-sale data flows
> through a Python EL pipeline, dbt transformations, and a Supabase warehouse,
> into a live five-view executive dashboard — refreshed automatically every night.

<p align="center">
  <!-- TODO(agent): confirm these badges match the repo's real CI + license -->
  <img alt="dbt" src="https://img.shields.io/badge/dbt-1.11-FF694B?logo=dbt&logoColor=white">
  <img alt="Postgres" src="https://img.shields.io/badge/Postgres-Supabase-3ECF8E?logo=postgresql&logoColor=white">
  <img alt="Next.js" src="https://img.shields.io/badge/Next.js-Vercel-000000?logo=nextdotjs&logoColor=white">
  <img alt="tests" src="https://img.shields.io/badge/dbt%20tests-179%20passing-3ECF8E">
</p>

<p align="center">
  <b><a href="https://analytics-engineer-website.vercel.app/projects/convenience-store/dashboard">▶ Open the live dashboard</a></b>
  &nbsp;·&nbsp;
  <a href="https://analytics-engineer-website.vercel.app/dbt-docs/index.html">dbt docs ↗</a>
  &nbsp;·&nbsp;
  <a href="#-architecture">Architecture</a>
  &nbsp;·&nbsp;
  <a href="#-live-executive-dashboard">Dashboard</a>
</p>

---

## What this project demonstrates

This is a portfolio project for an **Analytics Engineer** role. It covers the
full modern-data-stack workflow, end to end:

- **Ingesting real data** — a genuine Verifone Retail 360 point-of-sale backup
  from a small store, augmented with realistic synthetic sales and inventory
  cycles so the dataset is rich enough to model.
- **The EL → T pattern** — Python handles Extract & Load; dbt owns Transform.
- **Dimensional modelling** — staging → intermediate → marts (dims, facts,
  reporting), including slowly-changing-dimension snapshots and a
  point-in-time-correct inventory history.
- **Data quality as a first-class concern** — 179 dbt tests with a severity
  policy that separates source noise from integrity violations.
- **Serving & presentation** — a Supabase production warehouse and a live
  Next.js dashboard built for a store manager, not just for show.
- **Automation** — the whole pipeline runs unattended every night.

---

## 🏗 Architecture

<p align="center">
  <img src="./docs/pipeline_v3_github.svg" alt="Pipeline: three sources flow through an EL→T engine into a live dashboard" width="100%">
</p>

Three sources converge into one **EL → T** engine, which publishes to Supabase
and a live Next.js dashboard.

| Stage | Tool | What happens |
|-------|------|--------------|
| **Source** | Verifone Retail 360 `.bak` | Real SQL Server POS backup, restored locally |
| **Extract & Load** | Python · pandas · `uv` | SQL Server → local Postgres (`raw`), plus synthetic sales & inventory cycles |
| **Transform** | dbt 1.11 | `staging → intermediate → marts/core → marts/reporting` · ~39 models · 179 tests |
| **Serve** | Supabase Postgres | `dbt run --target prod` builds `dim_* / fct_* / rpt_*` |
| **Present** | Next.js on Vercel | Five-view executive dashboard, refreshed by a revalidate webhook |

<details>
<summary><b>dbt model layers</b></summary>

- **staging (`stg_*`)** — one model per source table; clean and rename only.
- **intermediate (`int_*`)** — sales line items, inventory velocity & stock
  health, workforce shifts.
- **marts/core (`dim_*`, `fct_*`)** — conformed dimensions and facts, including
  `fct_inventory_snapshot_history` (one point-in-time-correct snapshot per
  business day, built on a recursive date spine) and 2 SCD snapshots.
- **marts/reporting (`rpt_*`)** — dashboard-ready tables; the production surface
  the UI reads from.

</details>

---

## 📊 Live Executive Dashboard

A five-view operational dashboard built on the dbt reporting layer. Each view
answers one question a store manager actually asks.

> **[▶ Open the live dashboard](https://analytics-engineer-website.vercel.app/projects/convenience-store/dashboard)**

<p align="center">
  <img src="./docs/overview.jpg" alt="Overview — KPIs, sales and ticket trends, top products, stock split" width="100%">
</p>

<details>
<summary><b>📈 Overview</b> — "Is the store healthy right now?"</summary>
<br>
<img src="./docs/overview.jpg" alt="Overview view" width="100%">

Headline KPIs with a prior-period comparison baseline, daily revenue and
ticket-count trends (with a 7-day moving average and hover detail), the live
top-10 product ranking, and the current stock-status split.
</details>

<details>
<summary><b>🕐 Sales</b> — "When and how do we sell?"</summary>
<br>
<img src="./docs/sales.jpg" alt="Sales view" width="100%">

Daily sales and average-ticket trends, **sales by hour of day** (morning /
midday / evening / night) to find peak trading hours for staffing, and a
**cash-vs-credit payment mix** — useful for understanding card-processing fees.
</details>

<details>
<summary><b>📦 Inventory</b> — "What do I reorder or clear today?"</summary>
<br>
<img src="./docs/inventory.jpg" alt="Inventory view" width="100%">

Inventory health over time (at-risk items vs days of cover), stock-status mix
over time, a current stock-status distribution, and a days-of-cover
distribution. The view always reflects the **latest snapshot**, independent of
the date filter — and pairs with an actionable reorder plan.
</details>

<details>
<summary><b>🏷️ Products & Categories</b> — "What makes money vs dead weight?"</summary>
<br>
<img src="./docs/product___categories.jpg" alt="Products and categories view" width="100%">

Top products by revenue, **category revenue share**, and a **sales-vs-gross-profit
scatter** coloured by velocity band. A notable insight the data surfaces: one
category can dominate revenue while another drives margin.
</details>

<details>
<summary><b>👥 Workforce</b> — "Who performs, and what does labour cost?"</summary>
<br>
<img src="./docs/workforce.jpg" alt="Workforce view" width="100%">

A per-employee scorecard rankable by sales, hours, or efficiency; labour cost
split into regular vs overtime tiers; and daily attributed sales per employee.
Sales are attributed by **share of worked hours**, not direct transaction
ownership — and the dashboard says so, openly.
</details>

### How the dashboard is wired

<p align="center">
  <img src="./docs/dashboard_lineage_github.svg" alt="rpt_ reporting tables map to the five dashboard views" width="100%">
</p>

The dbt **reporting layer (`rpt_*`)** is the contract between transformation and
UI: the dashboard reads only `rpt_` tables — never `raw` or intermediate marts.

---

## ⏱ Automation

The pipeline runs unattended, once a day. **Windows Task Scheduler** wakes the
machine at `03:00` and runs `run_daily_backfill.bat` →
`full_auto_backfill.py --auto-run`. For each new business day it loads data,
takes the inventory snapshot, pushes to Supabase, runs `dbt run --target prod`,
and triggers the dashboard revalidate webhook. If the data is already current,
it exits cleanly as a safe no-op.

---

## 🛠 Tech stack

**Ingestion** Python · pandas · SQLAlchemy · pyodbc · uv  
**Transform** dbt 1.11  
**Warehouse** PostgreSQL (local dev) · Supabase (production)  
**Dashboard** Next.js · Vercel  
**Orchestration** Windows Task Scheduler

---

## 📁 Repository structure

<!-- TODO(agent): verify this tree against the actual repo and correct paths -->
```
.
├── scripts/                 # Python EL: restore, extract-load, snapshot, backfill
├── dbt/
│   ├── models/
│   │   ├── staging/         # stg_*
│   │   ├── intermediate/    # int_*
│   │   └── marts/
│   │       ├── core/        # dim_*, fct_*
│   │       └── reporting/   # rpt_*  (dashboard surface)
│   ├── snapshots/           # SCD snapshots
│   └── tests/               # data tests
├── docs/                    # diagrams + dashboard screenshots
└── README.md
```

---

## 👤 Author

**Zafrir Havia** — Analytics Engineer  
Transforming raw data into decisions, built with Next.js, dbt & Supabase.

<!--
  TODO(agent) — please adapt this README to the real repo:
  1. Verify every file path, model count, and table name against the codebase.
  2. Replace inferred rpt_ names in the lineage diagram with real model names.
  3. Confirm badge values (dbt version, test count, license).
  4. Add a LICENSE badge/section if one exists.
  5. Add real "getting started / how to run" steps if you want it reproducible,
     OR add a note that it's a portfolio project not meant to be run as-is.
  6. Fill author links (GitHub, LinkedIn, portfolio).
-->
