-- Federated graph learning silos. Each country's customer subgraph is a silo that may only be stored and
-- trained in that country's residency region (dim_country.residency_region); only model updates leave it.
-- Merchants and countries are public, non-personal nodes replicated into every silo.
-- Task carried as label: complaint in the 90 days after var('as_of_date') minus 90 days (PIT-safe cutoff).
{{ config(materialized='external', location=env_var('LATAM_LAKE_DIR', '../../data/lake') ~ '/graph/fgl_silo_nodes.parquet') }}
{% set cutoff = "date '" ~ var('as_of_date') ~ "' - interval 90 day" %}
with cust as (
    select
        p.customer_id,
        p.country_code                                         as silo,
        p.segment,
        coalesce(p.credit_score, 0)                            as credit_score,
        p.tenure_days,
        exists (select 1 from {{ ref('stg_complaints') }} k
                where k.customer_id = p.customer_id
                  and k.created_ts_utc >  {{ cutoff }}
                  and k.created_ts_utc <= {{ cutoff }} + interval 90 day) as label_complaint_90d
    from {{ ref('int_customer_profile') }} p
),
feat as (   -- behaviour before the cutoff only
    select customer_id,
           count(*)                                            as tx_count,
           sum(amount_usd)                                     as amount_usd,
           avg((transaction_status = 'Declined')::int)         as decline_rate,
           count(distinct merchant_name)                       as n_merchants
    from {{ ref('int_transactions_enriched') }}
    where transaction_ts_utc < {{ cutoff }}
    group by 1
)
select
    c.silo,
    d.residency_region,
    'customer'                                                 as node_type,
    c.customer_id                                              as node_key,
    dense_rank() over (partition by c.silo order by c.customer_id) - 1 as local_idx,
    c.segment,
    c.credit_score,
    c.tenure_days,
    coalesce(f.tx_count, 0)                                    as tx_count,
    ln(1 + coalesce(f.amount_usd, 0))                          as log_amount_usd,
    coalesce(f.decline_rate, 0)                                as decline_rate,
    coalesce(f.n_merchants, 0)                                 as n_merchants,
    c.label_complaint_90d
from cust c
left join feat f using (customer_id)
join {{ ref('dim_country') }} d on d.country_code = c.silo
union all
select s.silo, d.residency_region, 'merchant', m.merchant_name,
       (select count(*) from cust x where x.silo = s.silo) + dense_rank() over (partition by s.silo order by m.merchant_name) - 1,
       null, 0, 0, m.n_transactions, 0, 0, 0, null
from {{ ref('dim_merchant') }} m
cross join (select distinct silo from cust) s
join {{ ref('dim_country') }} d on d.country_code = s.silo
