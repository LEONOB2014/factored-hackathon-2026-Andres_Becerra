-- Edges of each federated silo (customer -> merchant, aggregated before the PIT cutoff), expressed in the
-- silo's local node indices so a client trains without seeing any other country's ids.
{{ config(materialized='external', location=env_var('LATAM_LAKE_DIR', '../../data/lake') ~ '/graph/fgl_silo_edges.parquet') }}
{% set cutoff = "date '" ~ var('as_of_date') ~ "' - interval 90 day" %}
with n as (select * from {{ ref('fgl_silo_nodes') }}),
e as (
    select t.customer_id, t.merchant_name, count(*) as n_tx, {{ exact_sum("t.amount_usd") }} as amount_usd
    from {{ ref('int_transactions_enriched') }} t
    where t.merchant_name is not null and t.transaction_ts_utc < {{ cutoff }}
    group by all
)
select
    c.silo,
    c.local_idx                       as src_idx,
    m.local_idx                       as dst_idx,
    e.n_tx,
    ln(1 + e.amount_usd)              as log_amount_usd
from e
join n c on c.node_type = 'customer' and c.node_key = e.customer_id
join n m on m.node_type = 'merchant' and m.node_key = e.merchant_name and m.silo = c.silo
