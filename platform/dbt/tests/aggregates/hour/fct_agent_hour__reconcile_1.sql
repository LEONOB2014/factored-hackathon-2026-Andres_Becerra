-- fct_agent_hour: sum(contacts) equals count(*) filter (where agent_id is not null) of its atomic source.
with l as (select sum(contacts) as v from {{ ref('fct_agent_hour') }}),
     r as (select count(*) filter (where agent_id is not null) as v from {{ ref('fct_interaction') }})
select l.v as aggregate_value, r.v as atomic_value from l, r
where abs(coalesce(l.v, 0) - coalesce(r.v, 0)) > 1e-6 * greatest(1, abs(coalesce(r.v, 0)))
