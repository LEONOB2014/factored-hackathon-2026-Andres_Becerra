-- fct_country_day: sum(complaints_opened) equals count(*) of its atomic source.
with l as (select sum(complaints_opened) as v from {{ ref('fct_country_day') }}),
     r as (select count(*) as v from {{ ref('fct_complaint') }})
select l.v as aggregate_value, r.v as atomic_value from l, r
where abs(coalesce(l.v, 0) - coalesce(r.v, 0)) > 1e-6 * greatest(1, abs(coalesce(r.v, 0)))
