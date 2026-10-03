-- Static node features for the temporal graph network, aligned with the integer ids of tgn_tx_events
-- (customers 0..n_c-1, merchants n_c..). Only PIT-safe or slowly varying attributes; no protected attributes.
{{ config(materialized='external', location=env_var('LATAM_LAKE_DIR', '../../data/lake') ~ '/graph/tgn_node_features.parquet') }}
with c as (
    select customer_id, dense_rank() over (order by customer_id) - 1 as idx
    from {{ ref('int_customer_profile') }}
),
n_c as (select count(*) as n from c),
m as (
    select merchant_name, dense_rank() over (order by merchant_name) - 1 as idx
    from (select distinct merchant_name from {{ ref('int_transactions_enriched') }} where merchant_name is not null)
)
select
    c.idx                                            as node_idx,
    'customer'                                       as node_type,
    p.customer_id                                    as node_key,
    p.country_code,
    p.segment,
    coalesce(p.credit_score, 0)                      as credit_score,
    coalesce(p.credit_score is null, true)           as credit_score_missing,
    p.tenure_days,
    ln(1 + coalesce(p.monthly_income_usd, 0))        as log_income_usd,
    null::varchar                                    as merchant_category
from c join {{ ref('int_customer_profile') }} p using (customer_id)
union all
select
    (select n from n_c) + m.idx, 'merchant', d.merchant_name, null, null, 0, true, null, 0, d.main_category
from m join {{ ref('dim_merchant') }} d using (merchant_name)
