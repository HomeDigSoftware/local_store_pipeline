{{ config(materialized='table', indexes=[{'columns': ['item_id'], 'unique': true}]) }}

-- Per-item stockout exposure over the accumulated snapshot history.
-- Grain: one row per item_id. Made possible by fct_inventory_snapshot_history
-- (a per-business-day time-series) — a single-day snapshot could never count days.
-- Answers "which products spend the most time empty / about to be empty?" by
-- counting the days each item sat in OUT_OF_STOCK or STOCKOUT_RISK, plus the
-- longest unbroken at-risk streak (the real availability pain, not just a total).

with history as (
    select *
    from {{ ref('fct_inventory_snapshot_history') }}
),

-- Map each snapshot_date to a dense global day index so a "consecutive days"
-- streak can be computed with integer arithmetic even if the history ever has gaps.
day_index as (
    select
        snapshot_date,
        dense_rank() over (order by snapshot_date) as day_seq
    from (select distinct snapshot_date from history) d
),

history_indexed as (
    select
        h.*,
        di.day_seq,
        (h.stock_status in ('OUT_OF_STOCK', 'STOCKOUT_RISK')) as is_at_risk
    from history h
    join day_index di on h.snapshot_date = di.snapshot_date
),

-- Gaps-and-islands: within an item's at-risk rows, (day_seq - row_number) is
-- constant across a run of consecutive days, so it identifies each streak.
at_risk_islands as (
    select
        item_id,
        snapshot_date,
        day_seq
            - row_number() over (partition by item_id order by day_seq) as streak_grp
    from history_indexed
    where is_at_risk
),

streaks as (
    select
        item_id,
        max(streak_len) as longest_at_risk_streak
    from (
        select item_id, streak_grp, count(*) as streak_len
        from at_risk_islands
        group by item_id, streak_grp
    ) s
    group by item_id
),

-- Carry the latest snapshot's status/attributes as the item's "current" state.
latest as (
    select distinct on (item_id)
        item_id,
        item_name,
        product_category_id,
        product_category_name,
        stock_status as current_stock_status
    from history
    order by item_id, snapshot_date desc
),

per_item as (
    select
        item_id,
        count(*) as total_snapshot_days,
        count(*) filter (where stock_status = 'OUT_OF_STOCK') as out_of_stock_days,
        count(*) filter (where stock_status = 'STOCKOUT_RISK') as stockout_risk_days,
        count(*) filter (where stock_status in ('OUT_OF_STOCK', 'STOCKOUT_RISK')) as at_risk_days,
        min(snapshot_date) filter (where stock_status in ('OUT_OF_STOCK', 'STOCKOUT_RISK')) as first_at_risk_date,
        max(snapshot_date) filter (where stock_status in ('OUT_OF_STOCK', 'STOCKOUT_RISK')) as last_at_risk_date
    from history
    group by item_id
)

select
    pi.item_id,
    l.item_name,
    l.product_category_id,
    l.product_category_name,
    pi.total_snapshot_days,
    pi.out_of_stock_days,
    pi.stockout_risk_days,
    pi.at_risk_days,
    round(pi.at_risk_days::numeric / nullif(pi.total_snapshot_days, 0) * 100, 1) as at_risk_pct,
    coalesce(s.longest_at_risk_streak, 0) as longest_at_risk_streak,
    pi.first_at_risk_date,
    pi.last_at_risk_date,
    l.current_stock_status,
    current_timestamp as dbt_loaded_at,
    'rpt_item_stockout_days' as dbt_source_relation
from per_item pi
inner join latest l on pi.item_id = l.item_id
left join streaks s on pi.item_id = s.item_id
order by pi.at_risk_days desc, pi.item_id
