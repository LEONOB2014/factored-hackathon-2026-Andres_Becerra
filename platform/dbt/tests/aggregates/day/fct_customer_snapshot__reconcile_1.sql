-- fct_customer_snapshot: sum(lifetime_tx) equals count(*) of its atomic source.
with l as (select sum(lifetime_tx) as v from {{ ref('fct_customer_snapshot') }}),
     r as (select count(*) as v from {{ ref('int_transactions_enriched') }})
select l.v as aggregate_value, r.v as atomic_value from l, r
where abs(coalesce(l.v, 0) - coalesce(r.v, 0)) > 1e-6 * greatest(1, abs(coalesce(r.v, 0)))
