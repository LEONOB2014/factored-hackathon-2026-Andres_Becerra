-- fct_agent_hour: sum(handle_seconds) equals sum(coalesce(duration_seconds, 0)) filter (where agent_id is not null) of its atomic source.
with l as (select sum(handle_seconds) as v from {{ ref('fct_agent_hour') }}),
     r as (select sum(coalesce(duration_seconds, 0)) filter (where agent_id is not null) as v from {{ ref('fct_interaction') }})
select l.v as aggregate_value, r.v as atomic_value from l, r
where abs(coalesce(l.v, 0) - coalesce(r.v, 0)) > 1e-6 * greatest(1, abs(coalesce(r.v, 0)))
