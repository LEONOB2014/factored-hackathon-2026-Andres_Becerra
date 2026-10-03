-- One row per data-quality rule: violations, rate against the table's row count, and the agreed SLO.
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
)
select
    s.rule_id,
    s.severity,
    s.table_name,
    s.description,
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
