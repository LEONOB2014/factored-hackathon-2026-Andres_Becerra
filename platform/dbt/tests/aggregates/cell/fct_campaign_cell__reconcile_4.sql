-- fct_campaign_cell: sum(send_cost) equals sum(coalesce(send_cost, 0)) of its atomic source.
with l as (select sum(send_cost) as v from {{ ref('fct_campaign_cell') }}),
     r as (select sum(coalesce(send_cost, 0)) as v from {{ ref('fct_campaign_send') }})
select l.v as aggregate_value, r.v as atomic_value from l, r
where abs(coalesce(l.v, 0) - coalesce(r.v, 0)) > 1e-6 * greatest(1, abs(coalesce(r.v, 0)))
