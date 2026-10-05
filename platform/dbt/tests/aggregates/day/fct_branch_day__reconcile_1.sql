-- fct_branch_day: sum(n_tx) equals count(branch_id) of its atomic source.
with l as (select sum(n_tx) as v from {{ ref('fct_branch_day') }}),
     r as (select count(branch_id) as v from {{ ref('int_transactions_enriched') }})
select l.v as aggregate_value, r.v as atomic_value from l, r
where abs(coalesce(l.v, 0) - coalesce(r.v, 0)) > 1e-6 * greatest(1, abs(coalesce(r.v, 0)))
