#!/usr/bin/env bash
# Demonstrates what SCD2 snapshots would have recorded if the backup folder had been an earlier load of
# the customer master and the main folder the next one. Run from platform/dbt/:  bash scripts/scd2_demo.sh
# It uses a separate DuckDB file so the regular warehouse is untouched.
set -euo pipefail
export DBT_PROFILES_DIR=.
export LATAM_DUCKDB_PATH=../../data/warehouse_scd2_demo.duckdb
rm -f "$LATAM_DUCKDB_PATH"

uv run dbt seed -q
echo "== load 1: backup folder as the 'previous' customer master"
LATAM_PARQUET_DIR=../../data/parquet_backup uv run dbt run -q --select stg_customers
uv run dbt snapshot -q --select snap_customers
echo "== load 2: main folder as the 'current' customer master"
LATAM_PARQUET_DIR=../../data/parquet uv run dbt run -q --select stg_customers
uv run dbt snapshot -q --select snap_customers
uv run dbt run -q --select audit_scd2_change_log

uv run python - <<'EOF'
import duckdb, os
c = duckdb.connect(os.environ["LATAM_DUCKDB_PATH"], read_only=True)
print(c.sql("""
  select count(*) filter (where dbt_valid_to is null) as current_versions,
         count(*) filter (where dbt_valid_to is not null) as closed_versions,
         count(distinct customer_id) as keys
  from snapshots.snap_customers""").df().to_string(index=False))
print(c.sql("""
  select f.field, count(*) as changes
  from (select unnest(changed_fields) as f from audit.audit_scd2_change_log)
  group by 1 order by 2 desc""").df().to_string(index=False))
EOF
