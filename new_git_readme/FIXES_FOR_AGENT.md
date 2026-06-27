# Dashboard & repo — defects and improvements to work through

A prioritised punch-list for working with the design/dev agent. Grouped by
severity. Each item: what's wrong, why it matters, suggested fix. Check items
off as you go.

Legend: 🔴 credibility / correctness · 🟠 clarity / UX · 🟢 polish / nice-to-have

---

## 🔴 P1 — Correctness & credibility (fix first)

### 1. Unit counts show decimals
- **Where:** Overview & Sales KPIs ("7,387.592" units), daily detail table ("330.36").
- **Why it matters:** Units sold read as whole numbers; decimals look like a bug and are the first thing a reviewer notices.
- **Fix:** Round unit counts to integers in the display layer. If a measure is genuinely weight, give it its own column labelled in kg.

### 2. Metrics contradict each other across views
- **Avg days of cover:** 50.8d (Inventory) vs 129.2d (Overview).
- **Dead stock:** 507 items (Overview/Inventory snapshot) vs 1,940 SKUs (Products).
- **Why it matters:** Conflicting headline numbers break trust in the whole dashboard.
- **Fix:** One definition per metric. If the scope genuinely differs (e.g. "30-day pace" vs "all SKUs"), label each number with its scope so the difference is intentional and explained.

### 3. Workforce attributed-sales scale doesn't reconcile with Sales view
- **Where:** Workforce shows ₪435K–439K attributed sales *per employee*; Sales view shows ~₪194K net sales for the store over the period.
- **Why it matters:** Three employees summing to ~₪1.3M can't reconcile with ₪194K store sales for the same window — looks like a period mismatch or a double-count.
- **Fix:** Confirm the time window and attribution math. Likely the employee figure spans a longer period or isn't normalised to store sales. Make the windows consistent, or label them clearly.

### 4. Junk / placeholder rows in tables
- **Where:** "Unknown Item" and "Uncategorized" at the top of the reorder list.
- **Why it matters:** Looks unhandled; undermines the polished impression.
- **Fix:** Filter, group under an "Uncategorized" bucket, or tag explicitly. Decide a rule for null product/category.

---

## 🟠 P2 — Clarity & UX (high impact)

### 5. Too much per view, not enough guidance
- **Where:** Inventory (very long), Products (treemap + 2 scatters + tables).
- **Why it matters:** A manager can't tell what matters most; the signal drowns.
- **Fix:** Establish visual hierarchy — lead each view with its 1–2 most important elements; collapse or move secondary detail below the fold.

### 6. Charts lack a "so what" takeaway
- **Where:** Every chart, especially the scatters.
- **Why it matters:** Charts show data; managers need the conclusion.
- **Fix:** Add one plain-language caption per chart, e.g. "Busiest 11:00–15:00 — staff accordingly" or "5 high-volume products earn thin margin — review pricing."

### 7. Category treemap is dominated by one slice
- **Where:** Products & Categories — tobacco ≈ 66%, everything else unreadable.
- **Why it matters:** The treemap can't be read; the interesting categories vanish.
- **Fix:** Replace with a **sorted horizontal bar of gross profit** (not revenue). It stays legible and tells the better story (margin leaders ≠ revenue leaders).

### 8. Long tables need capping
- **Where:** Inventory reorder list (1019+), category table (28), product scatter (100).
- **Why it matters:** Endless scroll; the actionable top isn't privileged.
- **Fix:** Show top 10–15 (most urgent / highest value) with a "show all" expander or CSV export.

### 9. Inventory should lead with the action plan
- **Where:** Inventory view ordering.
- **Why it matters:** The reorder action plan is the most valuable, decision-ready element — it's currently below the analytical charts.
- **Fix:** Put "Reorder now" and the action table at the top of the view. Lead with the action, support with the analysis.

---

## 🟢 P3 — Polish & enhancements (differentiators)

### 10. Add direction indicators to ALL KPIs
- Only Total Sales has an up/down arrow + %. Add the same comparison treatment to every KPI card so status reads in 3 seconds.

### 11. Sparklines inside KPI cards
- A tiny 30-day trend line inside each KPI card is the single most "executive" upgrade available.

### 12. Sales-by-hour → hour × weekday heatmap
- The current hour bar averages across all days. A heatmap ("Friday 14:00") is far more actionable for staffing.

### 13. Return RATE, not just absolute returns
- The returns table is dominated by high-volume items (they naturally return more). Add returns ÷ sales per product to surface genuinely problematic items.

### 14. Quadrant labels on scatters
- Label the inventory-vs-sales and sales-vs-GP scatters directly ("overstocked", "reorder", "high sales / low margin") so they read without the caption.

### 15. Cross-link Workforce ↔ Sales
- Plot sales-per-labour-hour against the hourly traffic pattern: "are we staffed when it's busy?" This cross-view insight is the most valuable single addition.

### 16. Keep the attribution caveat
- The "estimated by hour-share, not transaction ownership" note shows analytical maturity. Keep it — reviewers value honesty about data limits.

---

## Repo / README housekeeping (not dashboard)

### 17. Clean the repo root
- Files like `compilation_output.txt`, `table_list.csv`, `.backup/`, `work_info.md` look untidy in the root. Move to a folder or `.gitignore`.

### 18. Reproducibility note
- The pipeline needs SQL Server + Windows Task Scheduler + a local `.bak`, so nobody else can run it. Either add small seed/CSV demo data, or state clearly it's a portfolio project not meant to run as-is.

### 19. Correct inferred names in the lineage diagram
- The lineage SVG includes a few inferred `rpt_` names (`rpt_inventory_vs_sales`, `rpt_category_performance`, `rpt_employee_payroll`). Replace with the real model names.

### 20. Verify README facts
- Confirm model count (~39), test count (179), file paths, and badge values against the actual codebase before publishing.

---

## Suggested order to tackle with the agent
1. P1 items 1–4 (correctness) — these are quick and protect credibility.
2. P2 items 6 & 9 (captions + lead-with-action) — biggest clarity gain for least effort.
3. P2 items 5, 7, 8 (trimming & treemap).
4. P3 items as time allows; 11, 12, 15 are the standout differentiators.
5. Repo housekeeping 17–20 before sharing the link widely.
