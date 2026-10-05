-- fct_channel_hour: sum(amount_usd) equals sum(coalesce(amount_usd, 0)) of its atomic source.
with l as (select sum(amount_usd) as v from {{ ref('fct_channel_hour') }}),
     r as (select sum(coalesce(amount_usd, 0)) as v from {{ ref('int_transactions_enriched') }})
select l.v as aggregate_value, r.v as atomic_value from l, r
where abs(coalesce(l.v, 0) - coalesce(r.v, 0)) > 1e-6 * greatest(1, abs(coalesce(r.v, 0)))
