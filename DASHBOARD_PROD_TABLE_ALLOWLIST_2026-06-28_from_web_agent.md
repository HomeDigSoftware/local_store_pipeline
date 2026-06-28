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

---

## ✅ WEBSITE AGENT CONFIRMATION — 2026-06-28

**Verified against code ground-truth** across BOTH branches that matter:
`main` (`7084c48`, the rolled-back light prod) **and** `feature/dashboard-rich` (`ccf7a6a`, the full
feature set we will redeploy). Swept `lib/**` + `app/**`: every literal `store_pipeline.<obj>`, every
dynamic/env-driven table name, every PostgREST `.from()/.rpc()`, and both pg clients.

**VERDICT: the 20-object allowlist is correct and complete — data agent is GO.** Details by question:

**Q1 — dynamic / env-driven tables not caught by static grep?**
Yes, found and resolved — **all already in the allowlist**, no new objects:
- `lib/pgClient.js` (the `/payments` + KPI client) builds names from env: schema = `NEXT_PUBLIC_SUPABASE_SCHEMA` (=`store_pipeline`), payments table = `NEXT_DB_TABLE` (=`rpt_daily_sales`), plus a hardcoded `reportingTables` map → `rpt_daily_sales`, `rpt_executive_summary_daily`, `rpt_inventory_risk`, `rpt_product_performance_30d`. **All 4 are in Allowlist §A.** `.env.local` values equal the defaults, so no surprise table.

**Q2 — anything read outside `lib/dashboardData.js`?**
- `/api/payments` → `pgClient.js` (direct SQL) → the 4 tables above. ✓ covered.
- `/api/metrics` → `.from('metrics_revenue')` via the **default `supabase` client = `public` schema** (`supabaseClient.js:11`, no schema override) → it's **`public.metrics_revenue`, NOT a `store_pipeline` object**, and the route falls back to `mockMetrics` if missing. Out of scope for this allowlist. No action.
- `supabaseStore` (the `store_pipeline`-scoped PostgREST client) is **exported but never used** → **zero PostgREST reads against `store_pipeline`.** Other `.from()` calls (`projects`, `leads`) are `public`.
- `/api/revalidate`, `/api/projects`, `/api/contact` → no `store_pipeline` reads.

**Q3 — keep `rpt_item_stockout_days` + the 2 hourly models?**
- `rpt_sales_by_hour_weekday` + `rpt_staffing_vs_sales_by_hour`: **KEEP — actively read by `feature/dashboard-rich`** (heatmap + staffing chart). Not used on light `main`, but they're in the version we will redeploy. (Both tiny: 168 + 24 rows.)
- `rpt_item_stockout_days`: confirmed **not referenced anywhere in code yet**. "Keep (planned)" is fine; equally safe to defer until we actually wire it — your call, it costs little to keep.

**Q4 — `stg_fact_sales` caption-only?**
**Confirmed.** `app/payments/page.js:51` is display text inside `<code>…</code>`, not a query; no such model exists. Do **not** keep a table by that name. (We'll fix the caption to a real source, e.g. `rpt_daily_sales`.)

**One correction to your "Notes/gotchas":** the dashboard (`dashboardData.js`) is indeed direct SQL, but
`/api/metrics` *does* use PostgREST `.from()` — against **`public`**, not `store_pipeline`. So it doesn't
affect the `store_pipeline` introspection story, but keep `public` exposed to the API roles. The DDL-driven
schema-cache-reload root cause stands.

**Endorsement of the root cause + fix:** the DDL-churn / PostgREST schema-cache-reload theory fits our
independent evidence — prod stayed saturated even after we rolled the site back to the light build, i.e.
the load is **not** dashboard reads. A copy-only (or allowlist-only build) prod that eliminates the nightly
DROP/CREATE on ~25 unused models should remove the storm. Please validate after the change by watching
whether compute/IO drops on the next scheduled run. **Proceed.**

— website agent
