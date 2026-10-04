-- Partitions held by the schema-drift circuit breaker: at least one severity-A check in dq_schema_drift and
-- no release approved through the four-eyes flow (dq_partition_releases_active, from the correction log). Staging excludes their rows (macro not_held), so
-- nothing derived from a partition whose schema changed reaches gold, features or serving. The rows stay in
-- lossless bronze and in the typed models; the dbt_lakehouse DAG raises a compliance trigger per new hold.
select
    d.zone,
    d.table_name,
    d.partition_date,
    count(*)                                                                    as severe_checks,
    list(distinct d.check_name || ':' || d.column_name order by d.check_name || ':' || d.column_name) as reasons,
    min(d.checked_at)                                                           as held_at
from {{ ref('dq_schema_drift') }} d
where d.severity = 'A'
  and not exists (
      select 1 from {{ ref('dq_partition_releases_active') }} r
      where r.table_name = d.table_name and r.partition_date = d.partition_date
  )
group by all
