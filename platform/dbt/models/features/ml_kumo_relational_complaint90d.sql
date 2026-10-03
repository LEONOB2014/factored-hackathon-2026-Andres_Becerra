-- Training table for a relational foundation model (nvidia/Kumo-Relational, KumoRFM-style) and for
-- relational deep learning: entity = customer, task = "files a complaint in the next 90 days".
-- One row per (customer, cutoff); the label window starts strictly after the cutoff. Related tables
-- (transactions, contacts, digital events, products) are passed to the model filtered to ts < cutoff
-- at load time (see docs/strategy/07_graph_and_foundation_models.md for the loader).
{{ config(materialized='external', location=env_var('LATAM_LAKE_DIR', '../../data/lake') ~ '/features/ml_kumo_relational_complaint90d.parquet') }}
with cutoffs as (
    select cast(d as timestamp) as cutoff_ts
    from range(date '2024-01-01', {{ as_of() }} - interval 90 day, interval 3 month) r(d)
)
select
    c.customer_id,
    k.cutoff_ts,
    c.segment,
    c.country_code,
    c.tenure_days - date_diff('day', k.cutoff_ts, {{ as_of() }}::timestamp) as tenure_days_at_cutoff,
    exists (select 1 from {{ ref('stg_complaints') }} x
            where x.customer_id = c.customer_id
              and x.created_ts_utc >  k.cutoff_ts
              and x.created_ts_utc <= k.cutoff_ts + interval 90 day)                as label_complaint_90d,
    case when k.cutoff_ts < timestamp '2025-07-01' then 'train'
         when k.cutoff_ts < timestamp '2025-10-01' then 'valid' else 'test' end     as split
from {{ ref('int_customer_profile') }} c
cross join cutoffs k
where cast(c.registration_date as timestamp) < k.cutoff_ts
