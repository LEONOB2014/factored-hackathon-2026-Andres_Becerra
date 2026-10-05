-- fct_campaign_cell: sum(conversions) equals count(*) filter (where had_conversion) of its atomic source.
with l as (select sum(conversions) as v from {{ ref('fct_campaign_cell') }}),
     r as (select count(*) filter (where had_conversion) as v from {{ ref('fct_campaign_send') }})
select l.v as aggregate_value, r.v as atomic_value from l, r
where abs(coalesce(l.v, 0) - coalesce(r.v, 0)) > 1e-6 * greatest(1, abs(coalesce(r.v, 0)))
