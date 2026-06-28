# Dashboard prod allowlist — which `store_pipeline` objects the website actually reads
**Date:** 2026-06-28
**Why this exists:** Supabase is hitting free-tier resource limits. Root cause = the nightly
`dbt run --target prod` does `DROP`/`CREATE` on **all ~44 models**, but the dashboard reads only
a small subset. Each DDL triggers a PostgREST schema-cache reload (the `pg_timezone_names` +
recursive-introspection storm). Fix = deploy/keep in prod **only** the objects below; stop
building + drop the rest.

**Source of truth:** derived directly from the website repo
(`analytics_engineer_website/lib/dashboardData.js` + `app/`), by extracting every
`store_pipeline.<object>` reference. This is code-ground-truth, not a guess. **Pending the
website agent's confirmation** (see "Confirm with website agent" below).

---

## ✅ ALLOWLIST — keep in Supabase `store_pipeline` (deploy/copy these)

### A. Reporting tables the dashboard queries directly (14)
```
rpt_category_performance_30d
rpt_daily_sales
rpt_employee_productivity
rpt_executive_summary_daily
rpt_inventory_actions
rpt_inventory_health_trend
rpt_inventory_risk
rpt_payment_mix_daily
rpt_product_performance_30d
rpt_product_velocity
rpt_returns_analysis_daily
rpt_sales_by_hour
rpt_sales_trend_daily
rpt_workforce_productivity_summary
```

### B. Non-`rpt_` objects the dashboard queries directly (3) — would break if dropped
```
dim_product               -- joined for category_name / item names (filtered views, scatter, reorder list)
int_sales__daily_product  -- recomputes the daily series when a CATEGORY/ITEM filter is active
                          --   (rpt_daily_sales has no category dimension) — lib/dashboardData.js:192-267, 1076-1106
fct_employee_shift        -- workforce shift-level detail — lib/dashboardData.js:1324, 1345
```
> ⚠️ These two (`int_sales__daily_product`, `fct_employee_shift`) are exactly why we checked
> instead of assuming "rpt_ + dims only" — a naive rule would have dropped them and broken the
> sales filter + workforce views.

### C. Reporting tables built & deployed but NOT yet wired in the UI (3) — keep (planned)
```
rpt_item_stockout_days          -- delivered 2026-06-25, handoff sent, UI not wired yet
rpt_sales_by_hour_weekday       -- delivered 2026-06-27 (heatmap), UI not wired yet
rpt_staffing_vs_sales_by_hour   -- delivered 2026-06-27 (labour vs sales), UI not wired yet
```

**Allowlist total: 20 objects.**

---

## ❌ NOT read by the dashboard — safe to stop deploying / drop from prod
Everything else currently in `store_pipeline` (~25 tables), notably:
- **`fct_inventory_snapshot_history`** — **43 MB, the single largest object** in prod. The dashboard
  never reads it directly (it reads `rpt_inventory_risk` / `rpt_inventory_health_trend`, which are
  built *from* it in dev). In a copy-only model it stays in dev → **reclaim 43 MB**.
- All `stg_store_data__*` (staging), `fct_sales`, `int_*` except `int_sales__daily_product`,
  `dim_date`, `fct_inventory_snapshot`, snapshots, etc.

## Notes / gotchas
- `store_pipeline.stg_fact_sales` appears in `app/payments/page.js:51` but only as **display caption
  text** ("Live data from …"), not a query — and no such model exists (real staging is
  `stg_store_data__*`). **Not** in the allowlist; the caption may want updating.
- The dashboard reads via **direct server-side SQL** (`query('SELECT … FROM store_pipeline.…')`),
  not the PostgREST `.from()` client, so the introspection storm is driven by **DDL events
  (nightly dbt), not by dashboard reads**. Confirms the fix is "reduce nightly DDL + drop unused".

## Confirm with website agent
Please confirm this list is complete:
1. Any table fetched **dynamically** (env-driven name, runtime-built SQL) not caught by the static grep?
2. Anything read by **API routes / server actions / cron** outside `lib/dashboardData.js` + `app/`?
3. OK to treat `rpt_item_stockout_days` + the 2 new hourly models as "keep (planned)" — you'll wire them?
4. OK that `stg_fact_sales` is only a caption (we will NOT keep a table by that name)?
