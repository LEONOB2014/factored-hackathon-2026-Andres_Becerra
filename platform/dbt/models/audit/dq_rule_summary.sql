-- One row per data-quality rule and table: violations, rate against the table's row count, and the agreed SLO.
-- R-rules are row-level (dq_integrity_findings, seed dq_rule_slo); C-rules are cell-level breaches of the
-- source contracts (dq_cell_findings, seed dq_cell_rule_slo) counted over the rows that flow on to gold:
-- rows of a held partition are reported once, as C10, not as the breaches that held them.
-- The dq_slo_breach test fails the build when a rule degrades beyond its max_rate_pct.
with counts as (
    select rule_id, table_name, count(*) as violations
    from {{ ref('dq_integrity_findings') }}
    group by all
),
denominators as (
    select 'transactions' as table_name, count(*) as n from {{ ref('stg_transactions') }}
    union all select 'products', count(*) from {{ ref('stg_products') }}
    union all select 'customers', count(*) from {{ ref('stg_customers') }}
    union all select 'complaints', count(*) from {{ ref('stg_complaints') }}
    union all select 'call_center_interactions', count(*) from {{ ref('stg_call_center_interactions') }}
    union all select 'digital_events', count(*) from {{ ref('stg_digital_events') }}
    union all select 'campaign_sends', count(*) from {{ ref('stg_campaign_sends') }}
    union all select 'service_agents', count(*) from {{ ref('stg_service_agents') }}
    union all select 'call_transcripts', count(*) from {{ ref('stg_call_transcripts') }}
),
partitions as (
    select distinct zone, table_name, partition_date, n_rows from {{ ref('dq_partition_profile') }}
),
cell_counts as (
    select s.rule_id, f.table_name, count(distinct f.zone || '|' || f.source_file || '|' || f.record_no)::bigint as violations
    from {{ ref('dq_cell_findings') }} f
    join (select distinct rule_id, issue_code from {{ ref('dq_cell_rule_slo') }}) s using (issue_code)
    where not exists (
        select 1 from {{ ref('dq_partition_holds') }} h
        where h.table_name = f.table_name and h.partition_date = f.partition_date
    )
    group by all
    union all
    select 'C10', p.table_name, sum(p.n_rows)::bigint
    from partitions p
    join {{ ref('dq_partition_holds') }} h using (table_name, partition_date)
    group by all
),
cell_rules as (  -- every C-rule for every typed source table; a table-specific seed row overrides '*'
    select
        d.rule_id, d.severity, t.table_name, d.description,
        coalesce(o.baseline_rate_pct, d.baseline_rate_pct) as baseline_rate_pct,
        coalesce(o.max_rate_pct, d.max_rate_pct)           as max_rate_pct,
        coalesce(o.enforce_in_dev, d.enforce_in_dev)       as enforce_in_dev,
        t.n
    from (select * from {{ ref('dq_cell_rule_slo') }} where table_name = '*') d
    cross join (select table_name, sum(n_rows)::bigint as n from partitions group by 1) t
    left join {{ ref('dq_cell_rule_slo') }} o on o.rule_id = d.rule_id and o.table_name = t.table_name
)
select
    s.rule_id,
    s.severity,
    s.table_name,
    s.description                                           as rule_description,
    coalesce(c.violations, 0)                               as violations,
    d.n                                                     as table_rows,
    round(100.0 * coalesce(c.violations, 0) / d.n, 3)       as rate_pct,
    s.baseline_rate_pct,
    s.max_rate_pct,
    s.enforce_in_dev,
    100.0 * coalesce(c.violations, 0) / d.n > s.max_rate_pct as slo_breached
from {{ ref('dq_rule_slo') }} s
left join counts c using (rule_id)
left join denominators d on d.table_name = s.table_name
union all
select
    r.rule_id,
    r.severity,
    r.table_name,
    r.description,
    coalesce(c.violations, 0),
    r.n,
    round(100.0 * coalesce(c.violations, 0) / r.n, 3),
    r.baseline_rate_pct,
    r.max_rate_pct,
    r.enforce_in_dev,
    100.0 * coalesce(c.violations, 0) / r.n > r.max_rate_pct
from cell_rules r
left join cell_counts c using (rule_id, table_name)
