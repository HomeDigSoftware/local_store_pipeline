# Read-only diagnostic for Supabase load (Section 1 of SUPABASE_LOAD_REDUCTION_PLAN.md).
# Connects to SUPABASE_URL and prints: DB size, biggest tables, indexes, live activity,
# connections-by-app, and pg_stat_statements top queries. Safe / read-only.
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")
import sqlalchemy as sa
import pandas as pd

pd.set_option("display.max_colwidth", 110)
pd.set_option("display.width", 200)
e = sa.create_engine(os.environ["SUPABASE_URL"])


def show(title, sql):
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78)
    try:
        df = pd.read_sql(sa.text(sql), e)
        print(df.to_string(index=False) if len(df) else "(no rows)")
    except Exception as ex:
        print(f"[skip] {str(ex)[:160]}")


show("DB SIZE (vs 500 MB free limit)",
    "select pg_size_pretty(pg_database_size(current_database())) as db_size")

show("TOP 20 TABLES BY TOTAL SIZE (data+indexes)", """
    select schemaname as schema, relname as table,
           pg_size_pretty(pg_total_relation_size(relid)) as total_size,
           n_live_tup as rows
    from pg_stat_user_tables
    order by pg_total_relation_size(relid) desc
    limit 20
""")

show("TABLE COUNT PER SCHEMA (raw should be sources-only)", """
    select table_schema, count(*) as tables
    from information_schema.tables
    where table_schema in ('raw','store_pipeline')
    group by 1 order by 1
""")

show("INDEXES on store_pipeline + raw (expect FEW = problem)", """
    select schemaname as schema, tablename as table, indexname as index
    from pg_indexes
    where schemaname in ('raw','store_pipeline')
    order by 1,2
""")

show("LIVE CONNECTIONS by app + state (who is connected now)", """
    select coalesce(nullif(application_name,''),'?') as app, state, count(*) as conns
    from pg_stat_activity
    where datname = current_database()
    group by 1,2 order by 3 desc
""")

show("ACTIVE QUERIES RIGHT NOW (non-idle)", """
    select pid, state,
           round(extract(epoch from (now()-query_start))::numeric,1) as dur_s,
           left(regexp_replace(query,'\\s+',' ','g'),110) as query
    from pg_stat_activity
    where datname = current_database() and state <> 'idle'
      and pid <> pg_backend_pid()
    order by query_start
    limit 20
""")

show("pg_stat_statements — TOP 15 BY TOTAL TIME (biggest IO/CPU cost)", """
    select calls,
           round(total_exec_time::numeric,0) as total_ms,
           round(mean_exec_time::numeric,1) as mean_ms,
           round((100*total_exec_time/sum(total_exec_time) over ())::numeric,1) as pct,
           left(regexp_replace(query,'\\s+',' ','g'),95) as query
    from pg_stat_statements
    order by total_exec_time desc
    limit 15
""")

show("pg_stat_statements — TOP 15 BY CALLS (most frequent)", """
    select calls,
           round(mean_exec_time::numeric,1) as mean_ms,
           left(regexp_replace(query,'\\s+',' ','g'),95) as query
    from pg_stat_statements
    order by calls desc
    limit 15
""")

e.dispose()
print("\nDone.")
