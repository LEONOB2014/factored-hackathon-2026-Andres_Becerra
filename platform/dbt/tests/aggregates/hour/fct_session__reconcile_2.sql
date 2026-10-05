-- fct_session: sum(n_errors) equals count(*) filter (where event_type = 'Error') of its atomic source.
with l as (select sum(n_errors) as v from {{ ref('fct_session') }}),
     r as (select count(*) filter (where event_type = 'Error') as v from {{ ref('stg_digital_events') }})
select l.v as aggregate_value, r.v as atomic_value from l, r
where abs(coalesce(l.v, 0) - coalesce(r.v, 0)) > 1e-6 * greatest(1, abs(coalesce(r.v, 0)))
