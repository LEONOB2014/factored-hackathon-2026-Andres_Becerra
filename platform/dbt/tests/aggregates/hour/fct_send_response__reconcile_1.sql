-- fct_send_response: sum(n_sends) equals count(*) of its atomic source.
with l as (select sum(n_sends) as v from {{ ref('fct_send_response') }}),
     r as (select count(*) as v from {{ ref('fct_campaign_send') }})
select l.v as aggregate_value, r.v as atomic_value from l, r
where abs(coalesce(l.v, 0) - coalesce(r.v, 0)) > 1e-6 * greatest(1, abs(coalesce(r.v, 0)))
