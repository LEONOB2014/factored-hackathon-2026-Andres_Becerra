-- fct_branch_hour: sum(n_tx) equals count(*) filter (where channel in ('Branch', 'ATM') and branch_id is not null) of its atomic source.
with l as (select sum(n_tx) as v from {{ ref('fct_branch_hour') }}),
     r as (select count(*) filter (where channel in ('Branch', 'ATM') and branch_id is not null) as v from {{ ref('int_transactions_enriched') }})
select l.v as aggregate_value, r.v as atomic_value from l, r
where abs(coalesce(l.v, 0) - coalesce(r.v, 0)) > 1e-6 * greatest(1, abs(coalesce(r.v, 0)))
